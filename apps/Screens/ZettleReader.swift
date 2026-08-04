import Foundation

/// Where the Zettle Payments SDK plugs in.
///
/// The kiosk page hands us {orderId, amountMinor, currency, orderNo}; a real
/// driver wakes the Bluetooth-paired Zettle Reader 2 for that amount, the guest
/// taps their card, and the sale lands inside Zettle — which is what keeps the
/// certified-kassaregister story intact (the reader, not us, is the register).
///
/// Until credentials from developer.zettle.com exist, the stub answers "no
/// reader" immediately and the page falls back to the counter flow, exactly as
/// if the app were a plain browser.
protocol CardReaderDriver {
    func charge(amountMinor: Int, currency: String, reference: String,
                completion: @escaping (Bool) -> Void)
}

final class NoReaderConfigured: CardReaderDriver {
    func charge(amountMinor: Int, currency: String, reference: String,
                completion: @escaping (Bool) -> Void) {
        completion(false)
    }
}

enum CardReader {
    /// Swap for the Zettle SDK driver once developer.zettle.com approves the app.
    static let driver: CardReaderDriver = NoReaderConfigured()
}
