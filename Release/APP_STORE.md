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

## TestFlight activation

1. Account Holder accepts the updated Apple Developer Program agreement.
2. Finish the app record and connect the repository in the workflow above.
3. Create the **Close Circle** external group and add the four privately supplied
   tester emails. Keep emails and relationship notes out of the public repository.
4. Complete beta description, feedback/review contact, and export-compliance
   answers; submit the first external build for Beta App Review. After approval,
   enable automatic distribution for the group.
5. Verify a cloud build from `main`, followed by a TestFlight install and full
   import → split → mix → save/reopen flow on a physical iPhone.

A successful upload is not external beta approval. Apple can require review for
later builds too. This workflow does not publish an App Store release.

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
installation, and the first cloud delivery remain unverified.

Activation blocker observed 2026-10-30: Xcode says the Account Holder must accept
the updated Apple Developer Program License Agreement before adding this product
to Xcode Cloud. No cloud workflow or automatic distribution is active yet.

Apple references:
- https://developer.apple.com/documentation/xcode/configuring-your-first-xcode-cloud-workflow
- https://developer.apple.com/documentation/xcode/configuring-start-conditions
- https://developer.apple.com/documentation/xcode/writing-custom-build-scripts
