import Foundation
import UIKit

/// The Zettle Payments SDK integration point.
///
/// The kiosk page hands us {orderId, amountMinor, currency}; the driver wakes
/// the Bluetooth-paired Zettle Reader 2 for that amount, the guest taps their
/// card, and the sale lands inside Zettle's own system — receipts and reporting
/// in the same backoffice the restaurant already uses.
///
/// Everything below compiles WITHOUT the SDK. When the package from
/// https://github.com/iZettle/sdk-ios is added and a client ID from
/// developer.zettle.com is entered on the device, the real driver takes over —
/// no other code changes. (The charge call may need a one-line touch-up against
/// the exact SDK version's signature; it cannot compile until the SDK exists.)
protocol CardReaderDriver {
    /// Called once at app launch, before any payment.
    func start()
    /// True when a payment could plausibly succeed (SDK present + configured).
    var isAvailable: Bool { get }
    /// Present the merchant login (staff, once per device).
    func performLogin(from viewController: UIViewController)
    func charge(amountMinor: Int, currency: String, reference: String,
                completion: @escaping (Bool) -> Void)
}

#if canImport(iZettleSDK)
import iZettleSDK

/// Live driver — active as soon as the SDK package is in the project.
final class ZettleSDKDriver: CardReaderDriver {
    private var started = false

    var isAvailable: Bool { started }

    func start() {
        let clientID = AppConfig.shared.zettleClientID
        guard !clientID.isEmpty, !started else { return }
        do {
            // callbackURL must exactly match the redirect URI registered on the
            // Zettle Developer Portal: ichiban://zettle
            let auth = try iZettleSDKAuthorization(
                clientID: clientID,
                callbackURL: URL(string: "ichiban://zettle")!)
            iZettleSDK.shared().start(with: auth)
            started = true
        } catch {
            print("Zettle SDK init failed: \(error)")
        }
    }

    func performLogin(from viewController: UIViewController) {
        guard started else { return }
        iZettleSDK.shared().performLogin(from: viewController) { error in
            if let error { print("Zettle login: \(error)") }
        }
    }

    func charge(amountMinor: Int, currency: String, reference: String,
                completion: @escaping (Bool) -> Void) {
        guard started,
              let presenter = UIApplication.shared.connectedScenes
                  .compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController })
                  .first
        else { return completion(false) }
        let amount = NSDecimalNumber(value: amountMinor).dividing(by: 100)
        iZettleSDK.shared().charge(amount: amount,
                                   currency: currency,
                                   enableTipping: false,
                                   reference: reference,
                                   presentFrom: presenter) { payment, error in
            completion(payment != nil && error == nil)
        }
    }
}
#endif

final class NoReaderConfigured: CardReaderDriver {
    var isAvailable: Bool { false }
    func start() {}
    func performLogin(from viewController: UIViewController) {}
    func charge(amountMinor: Int, currency: String, reference: String,
                completion: @escaping (Bool) -> Void) {
        completion(false)
    }
}

enum CardReader {
    static let driver: CardReaderDriver = {
        #if canImport(iZettleSDK)
        return ZettleSDKDriver()
        #else
        return NoReaderConfigured()
        #endif
    }()
}
