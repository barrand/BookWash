#!/usr/bin/env python3
"""epub_clipper.py

Create a clipped version of an existing EPUB containing only a subset of chapters:
- First chapter
- One middle chapter
- Last chapter

It keeps:
- Original metadata (optionally appends " (Clipped)" to the title)
- Cover image and all non-XHTML resources (CSS, images, fonts)
- toc.ncx trimmed to included chapters
- content.opf spine and manifest updated

Usage:
  python scripts/epub_clipper.py input.epub output.epub [--count 3] [--append-title] [--verbose]

Limitations:
- Only supports EPUB 2 (OPF + NCX) layout.
- Does not rewrite internal hyperlinks between chapters.
- Keeps all non-XHTML resources even if unused.
"""
from __future__ import annotations
import argparse
import zipfile
import io
import sys
from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NAMESPACES = {
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'ncx': 'http://www.daisy.org/z3986/2005/ncx/'
}

for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix if prefix != 'dc' else 'dc', uri)

@dataclass
class OpfData:
    path: str
    tree: ET.ElementTree
    manifest: ET.Element
    spine: ET.Element
    metadata: ET.Element
    id_to_item: dict  # id -> (href, media-type)

@dataclass
class NcxData:
    path: str | None
    tree: ET.ElementTree | None
    navMap: ET.Element | None


def find_container_opf(zipf: zipfile.ZipFile) -> str:
    try:
        with zipf.open('META-INF/container.xml') as f:
            content = f.read().decode('utf-8', errors='replace')
        root = ET.fromstring(content)
        rootfile = root.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile')
        if rootfile is None:
            raise RuntimeError('rootfile element not found in container.xml')
        full_path = rootfile.attrib.get('full-path')
        if not full_path:
            raise RuntimeError('full-path attribute missing in rootfile')
        return full_path
    except KeyError:
        raise RuntimeError('META-INF/container.xml not found in EPUB')


def parse_opf(zipf: zipfile.ZipFile, opf_path: str) -> OpfData:
    with zipf.open(opf_path) as f:
        content = f.read().decode('utf-8', errors='replace')
    tree = ET.ElementTree(ET.fromstring(content))
    root = tree.getroot()

    manifest = root.find('opf:manifest', NAMESPACES)
    spine = root.find('opf:spine', NAMESPACES)
    metadata = root.find('opf:metadata', NAMESPACES)
    if manifest is None or spine is None:
        raise RuntimeError('manifest or spine not found in OPF')

    id_to_item = {}
    for item in manifest.findall('opf:item', NAMESPACES):
        id_attr = item.get('id')
        href = item.get('href')
        media_type = item.get('media-type')
        if id_attr and href and media_type:
            id_to_item[id_attr] = (href, media_type)

    return OpfData(opf_path, tree, manifest, spine, metadata, id_to_item)


def parse_ncx(zipf: zipfile.ZipFile, opf: OpfData) -> NcxData:
    # Find NCX via manifest item with media-type application/x-dtbncx+xml or id 'ncx'
    ncx_item_id = None
    for id_, (href, media_type) in opf.id_to_item.items():
        if media_type == 'application/x-dtbncx+xml' or id_ == 'ncx':
            ncx_item_id = id_
            break
    if not ncx_item_id:
        return NcxData(None, None, None)
    href = opf.id_to_item[ncx_item_id][0]
    ncx_path = str(Path(opf.path).parent / href) if '/' in opf.path else href
    try:
        with zipf.open(ncx_path) as f:
            content = f.read().decode('utf-8', errors='replace')
        tree = ET.ElementTree(ET.fromstring(content))
        navMap = tree.getroot().find('ncx:navMap', NAMESPACES)
        return NcxData(ncx_path, tree, navMap)
    except KeyError:
        return NcxData(None, None, None)


def gather_spine_ids(opf: OpfData) -> list[str]:
    ids = []
    for itemref in opf.spine.findall('opf:itemref', NAMESPACES):
        idref = itemref.get('idref')
        if idref:
            ids.append(idref)
    return ids


def extract_text_and_count_words(html_bytes: bytes) -> int:
    text = html_bytes.decode('utf-8', errors='replace')
    # Remove scripts/styles
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.I | re.S)
    # Strip tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse entities (simple) & whitespace
    text = re.sub(r'&[a-zA-Z0-9#]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return 0
    return len(re.findall(r'\w+', text))

def choose_content_indices(zipf: zipfile.ZipFile, opf: OpfData, spine_ids: list[str], count: int, min_words: int, verbose: bool) -> list[int]:
    """Select indices ensuring first/middle/last with >= min_words, falling back gracefully."""
    word_counts: list[int] = []
    opf_dir = str(Path(opf.path).parent)
    for idref in spine_ids:
        href, media_type = opf.id_to_item.get(idref, (None, None))
        if href is None:
            word_counts.append(0)
            continue
        chapter_path = str(Path(opf_dir) / href) if opf_dir else href
        try:
            with zipf.open(chapter_path) as f:
                data = f.read()
            wc = extract_text_and_count_words(data)
        except KeyError:
            wc = 0
        word_counts.append(wc)
    if verbose:
        print(f"Computed word counts for {len(spine_ids)} spine items.")
    # Build list of indices meeting threshold
    eligible = [i for i, wc in enumerate(word_counts) if wc >= min_words]
    if verbose:
        print(f"Eligible (>= {min_words} words): {eligible[:15]}{' ...' if len(eligible)>15 else ''}")
    if not eligible:
        # Fallback: just pick structural first/mid/last regardless of size
        if verbose:
            print("No chapters meet min word threshold; falling back to structural selection.")
        return _structural_indices(len(spine_ids), count)
    if len(eligible) <= count:
        return eligible
    # Ensure first and last eligible
    first_idx = eligible[0]
    last_idx = eligible[-1]
    # Middle eligible
    mid_idx = eligible[len(eligible)//2]
    chosen = sorted(set([first_idx, mid_idx, last_idx]))
    # If user requested more than 3, add additional spaced eligibles
    if len(chosen) < count:
        step = len(eligible) / (count - 1)
        for k in range(count):
            candidate = eligible[min(int(round(k * step)), len(eligible)-1)]
            chosen.append(candidate)
            if len(set(chosen)) == count:
                break
    return sorted(set(chosen))

def _structural_indices(total: int, count: int) -> list[int]:
    if total == 0:
        return []
    if total <= count:
        return list(range(total))
    middle = total // 2
    indices = sorted(set([0, middle, total - 1]))
    while len(indices) < count:
        step = total / (count - 1)
        candidates = [round(i * step) for i in range(count)]
        for c in candidates:
            if c not in indices and 0 <= c < total:
                indices.append(c)
            if len(indices) == count:
                break
    return sorted(indices)


def clip_opf(opf: OpfData, keep_idrefs: set[str], append_title: bool):
    # Adjust spine
    original_itemrefs = list(opf.spine.findall('opf:itemref', NAMESPACES))
    for itemref in original_itemrefs:
        if itemref.get('idref') not in keep_idrefs:
            opf.spine.remove(itemref)
    # Adjust manifest: remove xhtml items not in keep set if they were in spine
    for item in list(opf.manifest.findall('opf:item', NAMESPACES)):
        id_attr = item.get('id')
        media_type = item.get('media-type')
        if media_type == 'application/xhtml+xml' and id_attr not in keep_idrefs:
            # Only remove if it was part of reading order originally
            itemrefs_ids = gather_spine_ids(opf)
            if id_attr in itemrefs_ids:
                opf.manifest.remove(item)
    # Optionally modify title
    if append_title and opf.metadata is not None:
        title_el = opf.metadata.find('dc:title', NAMESPACES)
        if title_el is not None and not title_el.text.endswith(' (Clipped)'):
            title_el.text = f"{title_el.text} (Clipped)"


def clip_ncx(ncx: NcxData, keep_hrefs: set[str]):
    if not ncx.navMap:
        return
    # Map href forms to allow relative path variations
    def href_matches(src: str) -> bool:
        # Strip fragment portion
        base = src.split('#', 1)[0]
        return base in keep_hrefs
    navPoints = list(ncx.navMap.findall('ncx:navPoint', NAMESPACES))
    kept = []
    for nav in navPoints:
        content_el = nav.find('ncx:content', NAMESPACES)
        if content_el is None:
            continue
        src = content_el.get('src', '')
        if href_matches(src):
            kept.append(nav)
        else:
            ncx.navMap.remove(nav)
    # Reassign playOrder sequentially
    for idx, nav in enumerate(kept, start=1):
        nav.set('playOrder', str(idx))
        nav.set('id', f'navPoint-{idx}')


def build_output_epub(zipf: zipfile.ZipFile, opf: OpfData, ncx: NcxData, keep_href_set: set[str], output_path: Path, verbose: bool):
    # Prepare modified OPF and NCX XML strings
    opf_xml = io.BytesIO()
    opf.tree.write(opf_xml, encoding='utf-8', xml_declaration=True)
    ncx_xml = None
    if ncx.path and ncx.tree:
        ncx_xml = io.BytesIO()
        ncx.tree.write(ncx_xml, encoding='utf-8', xml_declaration=True)

    with zipfile.ZipFile(output_path, 'w') as out_zip:
        # Write mimetype first (stored, no compression)
        try:
            mimetype_data = zipf.read('mimetype')
            zi = zipfile.ZipInfo('mimetype')
            zi.compress_type = zipfile.ZIP_STORED
            out_zip.writestr(zi, mimetype_data)
        except KeyError:
            # EPUB spec requires mimetype first; create if missing
            zi = zipfile.ZipInfo('mimetype')
            zi.compress_type = zipfile.ZIP_STORED
            out_zip.writestr(zi, b'application/epub+zip')

        # Copy all original files except removed chapter xhtml + replaced OPF/NCX
        for name in zipf.namelist():
            if name == 'mimetype':
                continue
            if name == opf.path:
                # Will write modified opf later
                continue
            if ncx.path and name == ncx.path:
                continue
            # If it's an xhtml chapter we removed, skip
            if name.lower().endswith(('.xhtml', '.html')):
                # Compare href relative to OPF dir
                opf_dir = str(Path(opf.path).parent)
                rel = name[len(opf_dir)+1:] if opf_dir and name.startswith(opf_dir + '/') else name
                if rel not in keep_href_set:
                    if verbose:
                        print(f"Skipping removed chapter file: {name}")
                    continue
            data = zipf.read(name)
            out_zip.writestr(name, data)

        # Write modified OPF
        out_zip.writestr(opf.path, opf_xml.getvalue())
        if ncx.path and ncx_xml is not None:
            out_zip.writestr(ncx.path, ncx_xml.getvalue())

    if verbose:
        print(f"Wrote clipped EPUB: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Clip an EPUB to a subset of chapters.')
    parser.add_argument('input', help='Path to source EPUB')
    parser.add_argument('output', help='Path to clipped EPUB to create')
    parser.add_argument('--count', type=int, default=3, help='Number of chapters to keep (default: 3)')
    parser.add_argument('--append-title', action='store_true', help='Append " (Clipped)" to title')
    parser.add_argument('--min-words', type=int, default=1000, help='Minimum word count for a chapter to be considered (default: 1000)')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Input EPUB not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with zipfile.ZipFile(input_path, 'r') as zipf:
        opf_path = find_container_opf(zipf)
        opf = parse_opf(zipf, opf_path)
        ncx = parse_ncx(zipf, opf)

        spine_ids = gather_spine_ids(opf)
        if not spine_ids:
            print('No spine itemrefs found; cannot proceed.', file=sys.stderr)
            sys.exit(1)
        indices = choose_content_indices(zipf, opf, spine_ids, args.count, args.min_words, args.verbose)
        selected_ids = [spine_ids[i] for i in indices]
        keep_idrefs = set(selected_ids)

        if args.verbose:
            print(f"Spine length: {len(spine_ids)}; keeping indices: {indices}")
            print(f"Keeping idrefs: {selected_ids}")

        # Clip OPF
        clip_opf(opf, keep_idrefs, args.append_title)

        # Determine hrefs for kept chapters
        keep_hrefs = set()
        for idref in keep_idrefs:
            href, media_type = opf.id_to_item.get(idref, (None, None))
            if href:
                # Accept common HTML media types
                if media_type in ('application/xhtml+xml', 'text/html', 'application/x-dtbook+xml'):
                    keep_hrefs.add(href)

        # If we unexpectedly only kept 1 chapter, provide diagnostic hints (always print in verbose).
        if args.verbose and len(keep_hrefs) < len(keep_idrefs):
            print("Warning: fewer hrefs retained than idrefs.")
            for idref in keep_idrefs:
                href, media_type = opf.id_to_item.get(idref, (None, None))
                print(f"  idref={idref} media-type={media_type} href={href}")
            print("  (Only hrefs with HTML/XHTML media types are included.)")

        # Clip NCX
        clip_ncx(ncx, keep_hrefs)

        # Build output EPUB
        build_output_epub(zipf, opf, ncx, keep_hrefs, output_path, args.verbose)

    if args.verbose:
        print('Done.')

if __name__ == '__main__':
    main()
