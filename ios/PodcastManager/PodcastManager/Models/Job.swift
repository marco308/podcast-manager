import Foundation

struct Job: Codable, Identifiable {
    let id: String
    let name: String
    let nextRun: String?
    let lastRun: String?
    let type: String
    let isConfigurable: Bool
    let schedule: JobSchedule?
    let intervalMinutes: Int?
}

struct JobSchedule: Codable {
    let hour: Int
    let minute: Int
}

struct JobsStatusResponse: Codable {
    let jobs: [Job]
}

struct UpdateScheduleRequest: Encodable {
    let hour: Int
    let minute: Int
}

struct UpdateScheduleResponse: Codable {
    let message: String
    let nextRun: String
}
