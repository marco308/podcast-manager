import SwiftUI

struct SettingsScreen: View {
    @Environment(AuthService.self) private var authService
    @State private var jobs: [Job] = []
    @State private var jobsLoading = false
    @State private var jobsError: String?
    @State private var scheduleDate = Calendar.current.date(from: DateComponents(hour: 4, minute: 0))!
    @State private var isSavingSchedule = false
    @State private var showScheduleSaved = false
    @State private var scheduleError: String?

    var body: some View {
        NavigationStack {
            List {
                if let user = authService.currentUser {
                    Section("Account") {
                        HStack {
                            Image(systemName: "person.circle.fill")
                                .font(.title)
                                .foregroundStyle(Color.accentColor)
                            VStack(alignment: .leading) {
                                Text(user.displayName ?? "Spotify User")
                                    .font(.headline)
                                if let email = user.email {
                                    Text(email)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }

                Section {
                    if jobsLoading && jobs.isEmpty {
                        HStack {
                            Spacer()
                            ProgressView()
                            Spacer()
                        }
                    } else if jobs.isEmpty, let jobsError {
                        VStack(alignment: .leading, spacing: 8) {
                            Label(jobsError, systemImage: "exclamationmark.triangle")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Button("Retry") {
                                Task { await loadJobs() }
                            }
                            .font(.caption.weight(.semibold))
                        }
                        .padding(.vertical, 4)
                    } else {
                        ForEach(jobs) { job in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(job.name)
                                        .font(.subheadline.weight(.medium))
                                    Spacer()
                                    Text(job.type == "cron" ? "Scheduled" : "Interval")
                                        .font(.caption2)
                                        .padding(.horizontal, 6)
                                        .padding(.vertical, 2)
                                        .background(job.type == "cron" ? Color.blue.opacity(0.15) : Color.green.opacity(0.15))
                                        .foregroundStyle(job.type == "cron" ? .blue : .green)
                                        .clipShape(Capsule())
                                }

                                if let nextRun = job.nextRun {
                                    HStack(spacing: 4) {
                                        Image(systemName: "clock")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                        Text("Next: \(relativeTime(nextRun))")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }

                                if let lastRun = job.lastRun {
                                    HStack(spacing: 4) {
                                        Image(systemName: "checkmark.circle")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                        Text("Last: \(relativeTime(lastRun))")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }

                                if job.type == "interval", let interval = job.intervalMinutes {
                                    HStack(spacing: 4) {
                                        Image(systemName: "repeat")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                        Text("Every \(formatInterval(interval))")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }

                                if job.isConfigurable {
                                    Divider()
                                    HStack {
                                        DatePicker(
                                            "Update time",
                                            selection: $scheduleDate,
                                            displayedComponents: .hourAndMinute
                                        )
                                        .labelsHidden()

                                        Spacer()

                                        if isSavingSchedule {
                                            ProgressView()
                                                .controlSize(.small)
                                        } else if showScheduleSaved {
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundStyle(.green)
                                        } else if scheduleError != nil {
                                            Image(systemName: "exclamationmark.circle.fill")
                                                .foregroundStyle(.red)
                                        }

                                        Button("Save") {
                                            Task { await saveSchedule() }
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .controlSize(.small)
                                        .disabled(isSavingSchedule)
                                    }

                                    if let scheduleError {
                                        Text(scheduleError)
                                            .font(.caption)
                                            .foregroundStyle(.red)
                                    }
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                } header: {
                    Text("Scheduled Jobs")
                }

                Section("About") {
                    HStack {
                        Text("Server")
                        Spacer()
                        Text(ServerConfig.baseURL?.absoluteString ?? "Not configured")
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    HStack {
                        Text("Version")
                        Spacer()
                        Text(appVersion)
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Button("Sign Out", role: .destructive) {
                        Task { await authService.logout() }
                    }
                }
            }
            .navigationTitle("Settings")
            .task {
                await loadJobs()
            }
        }
    }

    /// "1.0 (6)", read from the bundle so it can't drift from the build.
    private var appVersion: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(version) (\(build))"
    }

    private func loadJobs() async {
        jobsLoading = true
        defer { jobsLoading = false }
        do {
            let response = try await APIClient.shared.fetchJobsStatus()
            jobs = response.jobs
            jobsError = nil
            // Set initial schedule from configurable job
            if let configurable = response.jobs.first(where: { $0.isConfigurable }),
               let schedule = configurable.schedule {
                scheduleDate = Calendar.current.date(from: DateComponents(hour: schedule.hour, minute: schedule.minute)) ?? scheduleDate
            }
        } catch {
            jobsError = "Couldn't load jobs: \(error.localizedDescription)"
        }
    }

    private func saveSchedule() async {
        let components = Calendar.current.dateComponents([.hour, .minute], from: scheduleDate)
        guard let hour = components.hour, let minute = components.minute else { return }

        isSavingSchedule = true
        defer { isSavingSchedule = false }
        scheduleError = nil

        do {
            _ = try await APIClient.shared.updateJobSchedule(hour: hour, minute: minute)
            showScheduleSaved = true
            await loadJobs()
            try? await Task.sleep(for: .seconds(2))
            showScheduleSaved = false
        } catch {
            scheduleError = "Couldn't save schedule: \(error.localizedDescription)"
        }
    }

    private func relativeTime(_ isoString: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        // Try with fractional seconds first, then without
        guard let date = formatter.date(from: isoString) ?? {
            formatter.formatOptions = [.withInternetDateTime]
            return formatter.date(from: isoString)
        }() else {
            return isoString
        }

        let relFormatter = RelativeDateTimeFormatter()
        relFormatter.unitsStyle = .abbreviated
        return relFormatter.localizedString(for: date, relativeTo: Date())
    }

    private func formatInterval(_ minutes: Int) -> String {
        if minutes >= 60 {
            let hours = minutes / 60
            let mins = minutes % 60
            if mins == 0 {
                return hours == 1 ? "hour" : "\(hours) hours"
            }
            return "\(hours)h \(mins)m"
        }
        return "\(minutes) min"
    }
}
