# StemSplitter beta delivery

## Branches and cloud workflow

Work on `dev`. Merge tested changes into `main` to release a beta.
Use **Xcode Cloud** for signing, build numbers, archives, and TestFlight delivery;
no distribution certificate or App Store private key belongs in GitHub.

Configure this workflow in Xcode (Integrate → Create Workflow), then manage it
in App Store Connect → StemSplitter → Xcode Cloud:

| Setting | Value |
| --- | --- |
| Product | StemSplitter, iOS |
| Bundle ID | `com.theaccessvirus.stemsplitter` |
| Team | `95JX3DQMJF` |
| Repository | `https://github.com/theaccessvirus/stemsplitter` (not upstream) |
| Workflow | Main → TestFlight |
| Start condition | Branch Changes: `main` only |
| Clean build | Enabled |
| Xcode | 26.3 or newer stable version compatible with iOS 26 |
| Action | Archive, iOS, scheme StemSplitter, Release |
| Distribution | TestFlight and App Store |
| Post-action | TestFlight external testing: Close Circle |

Xcode Cloud owns the workflow configuration in Apple's service; these settings
are not activated merely by committing this document. Let Cloud increment build
numbers; don't reset its next build number after uploads.

## Model dependency

`ci_scripts/ci_post_clone.sh` downloads the tested mixed-precision htdemucs Core ML
package from the pinned `coreml-htdemucs-v1` GitHub release and verifies SHA-256
before extraction. The archive includes model provenance. The release includes
Demucs's MIT license. No PyTorch/Python installation is needed on the cloud runner
or the phone. Model weights remain outside Git history.

Run the same bootstrap locally:

```sh
ci_scripts/ci_post_clone.sh
xcodebuild -project StemSplitter.xcodeproj -scheme StemSplitter \
  -destination 'generic/platform=iOS' -archivePath /tmp/StemSplitter.xcarchive \
  -allowProvisioningUpdates archive
```

## TestFlight operation

The **Close Circle** external group contains the four privately supplied testers.
Group ID: `4d9807da-8798-4b54-af5a-2402f36c14b6`. Public invitations are disabled.
The **Development** internal group exists as Apple's prerequisite for external groups.
Tester contact details stay in App Store Connect, not in this public repository.

Beta description, reviewer contact, feedback email, no-login instructions, and
build 2 test notes are saved. Build **1.0 (2)** is **Waiting for Review** as of
October 30, 2026, with **Automatically notify testers** enabled.

The workflow archives on `main` changes and uses the **TestFlight External Testing**
post-action for **Close Circle**. Editing is restricted to the Account Holder,
Admins, and App Managers, as Apple requires for external distribution.

Apple can require review for later builds too. This workflow does not publish an
App Store release. Next verification after approval: install using TestFlight on
a physical iPhone and exercise import → split → mix → save/reopen.

## Privacy and release validation

`Release/PrivacyInfo.xcprivacy` is included in Copy Bundle Resources. It declares
no tracking or developer-collected data, plus disk capacity checks (E174.1),
app-container file timestamps for saved history (C617.1), and host-time use for
synchronized playback (35F9.1). Reassess these declarations when functionality changes.

The app has optional Spotify/YouTube link fetching; do not claim it has no network
code. Local separation stays on device and saved splits persist in Application
Support. `privacy.html` describes this distinction. Review third-party service
behavior before finalizing App Store privacy labels and publish the policy URL.

Validated 2026-10-30: local signed Release archive succeeds with the model and
privacy manifest; cloud bootstrap download checksum passes. Earlier test-drive
results are in `../TEST-DRIVE.md`. Physical-device performance, external beta
installation remains unverified. Cloud builds 1 and 2 uploaded successfully;
build 2 passed processing and was submitted for external review.

Xcode Cloud workflow `Main → TestFlight` is active for changes to `main`.
Product: B43A526F-B53B-4F50-92FA-728DAA5ED2FD.
Workflow: 28B2B5BD-48E5-4591-95D1-4B9EE20D2174.
App Store Connect app: 6829064887. First cloud build started October 30, 2026.
The agreement warning was stale and cleared after restarting Xcode.
External tester distribution is configured for Close Circle. Build 2 is awaiting
Apple Beta App Review; invitations are set to notify testers automatically.

The build declares `ITSAppUsesNonExemptEncryption = NO`: the only network
encryption in this dependency-free app is Apple URLSession HTTPS. Reassess this
if adding cryptographic libraries or new networking implementations.

Apple references:
- https://developer.apple.com/documentation/xcode/configuring-your-first-xcode-cloud-workflow
- https://developer.apple.com/documentation/xcode/configuring-start-conditions
- https://developer.apple.com/documentation/xcode/writing-custom-build-scripts
