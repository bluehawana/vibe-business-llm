import SwiftUI

/// Shown once per iPad, on first launch. After that the device goes straight to
/// its screen; three fingers held on the display bring this back.
struct ScreenPicker: View {
    @ObservedObject private var config = AppConfig.shared
    let onPick: (Screen) -> Void

    var body: some View {
        NavigationStack {
            Form {
                Section("This iPad is") {
                    ForEach(Screen.allCases) { screen in
                        Button { onPick(screen) } label: {
                            Label {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(screen.title).font(.headline)
                                    Text(screen.detail).font(.caption).foregroundStyle(.secondary)
                                }
                            } icon: {
                                Image(systemName: screen.symbol)
                            }
                        }
                        .disabled(!config.isConfigured)
                    }
                }

                Section {
                    LabeledContent("Address") {
                        TextField("https://order.ichiban.biz", text: $config.serverURL)
                            .multilineTextAlignment(.trailing)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                    }
                    LabeledContent("Restaurant ID") {
                        TextField("db3c418e95a6", text: $config.projectID)
                            .multilineTextAlignment(.trailing)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                } header: {
                    Text("Server")
                } footer: {
                    Text("Changing the server here is all it takes to move to a new "
                         + "machine — the app never needs rebuilding for that.")
                }
            }
            .navigationTitle("Set up this iPad")
        }
    }
}
