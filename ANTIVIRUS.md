# Windows security warnings and signing

SmartScreen's **Windows protected your PC** message concerns application reputation.
A Defender **threat detected** message is an antivirus detection. Signing establishes
publisher identity and integrity; it does not guarantee either warning disappears.

## Executable and Setup installer

Use a trusted Authenticode code-signing certificate. Self-signed certificates do
not establish public publisher trust. Microsoft states that EV certificates no
longer grant an immediate SmartScreen bypass; signed new files can still need
reputation. GitHub hosting alone does not guarantee trust.

Install the Windows SDK signing tools and your certificate in the current user's
certificate store, then run:

```powershell
py -3.14 build.py --sign --certificate-thumbprint YOUR_CERTIFICATE_SHA1_THUMBPRINT
```

Alternatively, use `sign.bat YOUR_CERTIFICATE_SHA1_THUMBPRINT`.
The build signs the launcher using SHA-256 with an RFC 3161 timestamp, verifies the signature
and timestamp, and only then generates the ZIP and Setup. It also signs the finished
Setup before generating its SHA-256 file. No private key
or password is stored in the repository. Hardware/cloud providers may need their
own signing integration instead of the local certificate-store script.

The build disables UPX and embeds file/product version information. These are
packaging improvements, not a promise of fewer detections. Test the final signed
release on a clean Windows machine. If Defender flags it incorrectly, submit
that exact binary to [Microsoft's file review](https://www.microsoft.com/en-us/wdsi/filesubmission).

## Microsoft Store

Microsoft documents that **MSIX distributed through the Microsoft Store** is
signed by Microsoft and avoids SmartScreen download warnings. A traditional
EXE listed in the Store is a different distribution route.

HexLauncher ships a traditional Setup and portable EXE. A Store edition requires
packaging, certification, moving writable game/settings data out of the package
directory, and using Store updates rather than executable self-replacement.

References: [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation),
[code-signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).
