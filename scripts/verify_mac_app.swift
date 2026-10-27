// Native release acceptance: Launch Services must create a regular, active app.
// Run only with verify_built_app.py's generated workspace and isolated environment.
import AppKit
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

guard CommandLine.arguments.count == 2,
      ProcessInfo.processInfo.environment["PAPERFACT_DATA"] != nil,
      ProcessInfo.processInfo.environment["PAPERFACT_SMOKE_SECONDS"] != nil else {
    fail("Expected a bundle path and an isolated smoke-test environment")
}
let bundle = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
let configuration = NSWorkspace.OpenConfiguration()
configuration.createsNewApplicationInstance = true
configuration.activates = true
configuration.arguments = ["--paper", "demo:paperfact"]
configuration.environment = ProcessInfo.processInfo.environment
var launched: NSRunningApplication?
var launchError: Error?
var completed = false
NSWorkspace.shared.openApplication(at: bundle, configuration: configuration) { app, error in
    launched = app
    launchError = error
    completed = true
}
let launchDeadline = Date().addingTimeInterval(20)
while !completed && Date() < launchDeadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
}
guard completed, launchError == nil, let app = launched else {
    fail("Launch Services did not launch the test bundle")
}
let activationDeadline = Date().addingTimeInterval(15)
var active = false
while !app.isTerminated && Date() < activationDeadline {
    if app.activationPolicy == .regular {
        _ = app.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        if app.isActive {
            active = true
            break
        }
    }
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
}
// Request a normal close; the app's smoke deadline is a fallback, never force quit.
_ = app.terminate()
let closeDeadline = Date().addingTimeInterval(15)
while !app.isTerminated && Date() < closeDeadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
}
guard active else { fail("Paperfact did not become a regular active macOS app") }
guard app.isTerminated else { fail("The test app did not close normally") }
print("{\"passed\":true,\"launch_services\":true,\"regular_activation_policy\":true,\"became_active\":true,\"closed_normally\":true}")
