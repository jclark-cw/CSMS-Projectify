Projectify — Contract to Asana
==============================

WHAT IT DOES
  You drag in a signed sponsorship contract PDF. It reads the deliverables,
  shows you the sections and tasks it plans to create, you adjust anything that
  looks wrong, and then it builds the project in Asana.

  The contract stays on your machine. Nothing is uploaded anywhere except the
  project structure you approve, which goes to Asana.


RUNNING IT
  1. Unzip this folder somewhere permanent -- your Desktop or Documents is fine.
     Run it from the unzipped folder, not from inside the .zip.

  2. Double-click Projectify.exe

  3. Windows will show a blue "Windows protected your PC" box.
     This is expected: the app is not code-signed, which is a deliberate choice
     for an internal tool. Click "More info", then "Run anyway".

     You'll see this again on every updated build we send you, not just the
     first one -- Windows tracks the exact file, so a new version looks new to
     it. Nothing is wrong.

  4. First launch asks for your Asana details. See SETUP below.


SETUP (first launch only)
  You will be asked for an Asana Personal Access Token. To get one:

    - Go to https://app.asana.com/0/my-apps
    - Click "Create new token", name it "Projectify", copy the token
    - Paste it into the app

  Then pick your workspace and team from the dropdowns. That's it -- the token
  is stored in Windows Credential Manager, not in a file, and you won't be
  asked again.


USING IT
  - Drag a contract PDF onto the window (or click to browse).
  - Review the preview. Sections and tasks come straight from the contract, so
    check them against the document -- edit names, assignees, and due dates
    here before building.
  - Click "Create in Asana" and confirm.
  - Re-running the same contract will NOT create a duplicate; it tells you the
    project already exists and offers to build another only if you insist.


IF SOMETHING GOES WRONG
  App won't start at all:
    Windows 10 machines occasionally lack the Microsoft Edge WebView2 Runtime,
    which the app uses to draw its window. Install the free "Evergreen
    Bootstrapper" from Microsoft and try again:
    https://developer.microsoft.com/microsoft-edge/webview2/

  The preview is missing sections, or has junk in it:
    That's the PDF parsing, and it's the part most worth reporting. Please send
    back the contract PDF (or a screenshot of the preview next to the contract)
    so the heuristics can be adjusted.

  Anything else:
    Send a screenshot. Note what you clicked just before.


KNOWN LIMITATIONS IN THIS TEST BUILD
  - Not code-signed, hence the SmartScreen warning above. This is intentional and
    won't change -- the app is internal-only.
  - If a build fails partway through, it can leave a partly-created project in
    Asana. Delete it in Asana before retrying.
  - Asana members with private profiles show up as "Private User" in the
    assignee dropdowns and can't be told apart.
