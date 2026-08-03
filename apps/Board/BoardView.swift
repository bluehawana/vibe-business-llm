import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// The guest board, read from across a dining room. Same two columns as the web
/// version: numbers move Preparing → Ready and pulse while they're new.
struct BoardView: View {
    @StateObject private var model = BoardModel()
    @ObservedObject private var settings = AppConfig.shared
    @State private var showSettings = false
    @State private var pulse = false

    var body: some View {
        ZStack {
            Color(red: 0.07, green: 0.08, blue: 0.06).ignoresSafeArea()

            VStack(spacing: 0) {
                header
                HStack(spacing: 0) {
                    column(title: "Tillagas", subtitle: "Preparing",
                           tint: Color(red: 0.89, green: 0.72, blue: 0.23),
                           orders: model.preparing, big: false)
                    Rectangle().fill(Color.white.opacity(0.12)).frame(width: 2)
                    column(title: "Klar", subtitle: "Ready — collect your food",
                           tint: Color(red: 0.32, green: 0.72, blue: 0.53),
                           orders: model.ready, big: true)
                }
                footer
            }
        }
        .onAppear {
            model.start()
            // A board that goes to sleep is not a board.
            #if os(tvOS)
            UIApplication.shared.isIdleTimerDisabled = true
            #endif
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
                pulse = true
            }
        }
        .onDisappear { model.stop() }
        // Play/Pause opens setup — nothing a guest would press by accident, and
        // it means moving the server never needs Xcode.
        .onPlayPauseCommand { showSettings = true }
        .sheet(isPresented: $showSettings) { BoardSetupView() }
    }

    private var header: some View {
        HStack(spacing: 16) {
            Text("🍣").font(.system(size: 44))
            Text("Ichiban Sushi")
                .font(.system(size: 44, weight: .bold))
                .foregroundStyle(Color(red: 0.88, green: 0.63, blue: 0.10))
            if model.stale {
                Label("Ingen kontakt med servern", systemImage: "wifi.exclamationmark")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Color(red: 0.85, green: 0.42, blue: 0.32))
            }
        }
        .padding(.vertical, 24)
    }

    private func column(title: String, subtitle: String, tint: Color,
                        orders: [BoardOrder], big: Bool) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(title).font(.system(size: 40, weight: .bold)).foregroundStyle(tint)
                    Text(subtitle).font(.system(size: 26)).foregroundStyle(tint.opacity(0.6))
                }
                Rectangle().fill(tint).frame(height: 4)
            }

            if orders.isEmpty {
                Text("—").font(.system(size: 40)).foregroundStyle(.white.opacity(0.25))
            } else {
                // Wide enough for four digits at this size — a number that wraps
                // to two lines ("10" over "3") is a number a guest misreads.
                // A maximum as well as a minimum: without it the grid stretches
                // cells to fill the column and numbers drift apart, which reads
                // as "these are unrelated" from across a room.
                LazyVGrid(columns: [GridItem(.adaptive(minimum: big ? 280 : 210,
                                                       maximum: big ? 300 : 230),
                                             spacing: 24, alignment: .leading)],
                          alignment: .leading, spacing: 20) {
                    ForEach(orders) { order in
                        numberTile(order, tint: tint, big: big)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 44)
        .padding(.top, 16)
    }

    private func numberTile(_ order: BoardOrder, tint: Color, big: Bool) -> some View {
        Text(order.order_no)
            .font(.system(size: big ? 96 : 72, weight: .heavy, design: .rounded))
            .monospacedDigit()
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
            .foregroundStyle(big ? Color(red: 0.55, green: 0.94, blue: 0.71)
                                 : Color(red: 0.94, green: 0.84, blue: 0.44))
            .padding(.horizontal, 28).padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 18)
                    .fill(big ? Color(red: 0.11, green: 0.25, blue: 0.16)
                              : Color(red: 0.18, green: 0.16, blue: 0.08))
                    .overlay(RoundedRectangle(cornerRadius: 18)
                        .stroke(big ? tint : .clear, lineWidth: 3))
            )
            .scaleEffect(big && model.isFresh(order) && pulse ? 1.06 : 1.0)
    }

    private var footer: some View {
        Text("Ditt nummer står på kvittot  ·  Your number is on your receipt")
            .font(.system(size: 22))
            .foregroundStyle(.white.opacity(0.35))
            .padding(.vertical, 18)
    }
}

struct BoardSetupView: View {
    @ObservedObject private var settings = AppConfig.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            Text("Board setup").font(.system(size: 44, weight: .bold))
            Text("Point this Apple TV at the server. No rebuild needed when the server moves.")
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 8) {
                Text("Server URL").font(.headline)
                TextField("https://order.ichiban.biz", text: $settings.serverURL)
                    .textContentType(.URL)
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("Restaurant ID").font(.headline)
                TextField("db3c418e95a6", text: $settings.projectID)
            }
            Button("Done") { dismiss() }
            Spacer()
        }
        .padding(60)
    }
}
