# BookWash: AI-Powered Content Moderation for eBooks

Did you ever quit reading a book because there was just too much d\*mn profanity? Or racy scenes that made you uncomfortable? Maybe you wanted to share a great story with a younger reader, but the content was just a little too mature.

If you've ever wished you could just *wash* the questionable parts out of a book, then **BookWash is for you!**

BookWash is a desktop application built with Flutter that allows you to "wash" your EPUB books. It uses the power of Google's Gemini AI to analyze and filter content based on your preferred sensitivity levels.

![BookWash Setup Screen](https://i.imgur.com/8P2JXcH.png) 
Here is the setup screen that you'll see when running the app.

![BookWash In Action](https://i.imgur.com/DnLEmBJ.png)
Here is the cleaning screen when the app is doing it's magic.

## Features

*   **Process EPUB Files**: Select any EPUB file from your local drive.
*   **Customizable Filtering**: Set your desired content rating (G, PG, PG-13, R) for three categories:
    *   Profanity
    *   Sexual Content
    *   Violence
*   **AI-Powered Moderation**: Leverages the Google Gemini API to intelligently rate each chapter and then filter content that exceeds your chosen rating.
*   **Smart Two-Pass System**:
    1.  **Rating Pass**: The AI first reads and rates each chapter without modifying it.
    2.  **Filtering Pass**: If a chapter's rating is more explicit than your setting, the AI will perform a second pass to clean it, rephrasing or removing inappropriate content while trying to preserve the narrative. This saves time and reduces API calls.
*   **Live Log**: See the app's progress in real-time as it processes your book chapter by chapter, including which chapters are being filtered and which are being skipped.
*   **Generates New EPUB**: Outputs a new, cleaned EPUB file with `_cleaned` appended to the original filename. Your original file is never modified.

## How It Works

BookWash reads an EPUB file, breaks it down into its constituent chapters, and then processes each chapter's text through Google's Gemini API.

1.  **Chapter Rating**: Each chapter is sent to Gemini to get a content rating (G, PG, PG-13, R, or X) for profanity, sexual content, and violence.
2.  **Conditional Filtering**: The app compares the AI's rating to your selected sensitivity level. If the chapter's content is rated higher than your preference (e.g., rated 'R' for sexual content when you've selected 'PG'), it proceeds to the filtering step. Otherwise, it skips the chapter.
3.  **Content Cleaning**: For chapters that need it, the text is sent back to Gemini with a detailed prompt instructing it to remove or rephrase the inappropriate content according to your rating. The prompt engineering is designed to be very strict, especially at G and PG levels, prioritizing content safety over narrative preservation if necessary.
4.  **EPUB Re-creation**: Once all chapters are processed, a new EPUB file is assembled with the cleaned content.

## Getting Started

### Prerequisites

*   [Flutter SDK](https://docs.flutter.dev/get-started/install) installed on your system.
*   An editor like [VS Code](https://code.visualstudio.com/) or [Android Studio](https://developer.android.com/studio).
*   A **Google Gemini API Key**.
*   **For Windows Users**: You must have [Visual Studio](https://visualstudio.microsoft.com/downloads/) installed with the **"Desktop development with C++"** workload. This is required for building Flutter apps on Windows.

### Installation & Running

1.  **Clone the repository:**
    *   Open your preferred command-line tool (like PowerShell or Command Prompt on Windows, or Terminal on macOS).
    ```bash
    git clone https://github.com/barrand/BookWash.git
    cd BookWash
    ```

2.  **Get a Google Gemini API Key:**
    *   Navigate to the [Google AI for Developers](https://ai.google.dev/) website.
    *   Click on **"Get API key in Google AI Studio"**. You may need to sign in with your Google account.
    *   Once in the AI Studio, look for a **"Get API key"** option (often on the left-hand menu or top right).
    *   Click **"Create API key in new project"**.
    *   A new key will be generated. Click the copy icon next to the long string of letters and numbers.
    *   **Important:** Keep this key safe and private!

3.  **Run the App:**
    *   When you first launch the BookWash application, it will prompt you to enter your Gemini API key. Paste the key you just copied. The app will save it securely for future sessions.
    *   Run the app from your terminal using the command for your operating system:

    **On Windows:**
    ```bash
    flutter run -d windows
    ```

    **On macOS:**
    ```bash
    flutter run -d macos
    ```

    **On Linux:**
    ```bash
    flutter run -d linux
    ```


## Disclaimer & Limitations of AI Content Moderation

**This is an experimental tool. The AI is not perfect and is subject to errors, biases, and inconsistencies.**

*   **Accuracy is Not Guaranteed**: The AI misses content that should be filtered or may be overly aggressive and remove content that is benign. The quality of the output can vary significantly based on the complexity and nuance of the source material.
*   **Narrative Impact**: While the AI is instructed to preserve the story, removing or rephrasing content can inevitably alter the narrative, change the tone, or create plot holes. This is especially true at stricter filtering levels (G and PG).
*   **Context and Nuance**: AI models can struggle with context, sarcasm, and literary nuance. A passage may be flagged as inappropriate when it is not, or vice-versa.
*   **Rate Limiting**: The app uses the free tier of the Gemini API, which has rate limits. Processing very long books may cause the app to hit these limits, in which case it will automatically pause and retry. This can significantly increase processing time.
*   **Subjectivity**: What one person considers "PG" another might consider "PG-13". The AI's interpretation is based on its training data and the prompts provided, and may not perfectly align with every user's personal standards.

**Use this tool at your own discretion. Always review the output to ensure it meets your expectations.**
