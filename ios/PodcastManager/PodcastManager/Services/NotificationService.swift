import UIKit
import UserNotifications

@MainActor
final class NotificationService: Sendable {
    static let shared = NotificationService()

    private init() {}

    /// Request notification permission from the user.
    func requestAuthorization() async {
        do {
            let granted = try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .sound])
            if granted {
                print("[NotificationService] Notification permission granted")
            } else {
                print("[NotificationService] Notification permission denied")
            }
        } catch {
            print("[NotificationService] Authorization error: \(error)")
        }
    }

    /// Schedule a local notification only if the app is not in the foreground.
    /// - Parameters:
    ///   - title: The notification title.
    ///   - body: The notification body text.
    ///   - identifier: A unique identifier for this notification.
    func sendIfBackgrounded(title: String, body: String, identifier: String? = nil) {
        // Only send when the app is not active (backgrounded or inactive)
        guard !isAppInForeground else { return }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let id = identifier ?? UUID().uuidString
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 0.1, repeats: false)
        let request = UNNotificationRequest(identifier: id, content: content, trigger: trigger)

        UNUserNotificationCenter.current().add(request) { error in
            if let error {
                print("[NotificationService] Failed to schedule notification: \(error)")
            }
        }
    }

    // MARK: - Private

    private var isAppInForeground: Bool {
        UIApplication.shared.applicationState == .active
    }
}
