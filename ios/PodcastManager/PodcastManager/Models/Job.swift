import Foundation

struct Job: Codable, Identifiable {
    let id: String
    let name: String
    let nextRun: String?
    let lastRun: String?
    let type: String
    let isConfigurable: Bool
    /// First run time only; `scheduleTimes` has them all.
    let schedule: JobSchedule?
    /// Every run time, in order. Absent from servers that predate running
    /// the library sync + playlist update more than once a day.
    var scheduleTimes: [JobSchedule]? = nil
    var maxScheduleTimes: Int? = nil
    let intervalMinutes: Int?

    /// The run times, falling back to `schedule` for older servers.
    var runTimes: [JobSchedule] {
        scheduleTimes ?? schedule.map { [$0] } ?? []
    }
}

struct JobSchedule: Codable, Hashable {
    let hour: Int
    let minute: Int
}

struct JobsStatusResponse: Codable {
    let jobs: [Job]
}

struct UpdateScheduleRequest: Encodable {
    let times: [JobSchedule]
    /// The first time again, for servers that only understand one.
    let hour: Int
    let minute: Int

    init(times: [JobSchedule]) {
        self.times = times
        self.hour = times.first?.hour ?? 0
        self.minute = times.first?.minute ?? 0
    }
}

struct UpdateScheduleResponse: Codable {
    let message: String
    let nextRun: String
}
