import Foundation

struct BirdmarkUser: Codable, Identifiable, Equatable {
    let id: Int
    let email: String
    let username: String
    let displayName: String
    let avatarPath: String?
    let role: String?
    let status: String?
    let createdAt: String?
}

struct RegisterRequest: Encodable {
    let email: String
    let username: String
    let password: String
    let displayName: String
}

struct LoginRequest: Encodable {
    let identifier: String
    let password: String
}

struct AuthResponse: Codable {
    let accessToken: String
    let tokenType: String
    let user: BirdmarkUser
}

struct CurrentUserResponse: Codable {
    let user: BirdmarkUser
}

struct StatusResponse: Codable {
    let status: String
}

struct PhotoListResponse: Codable {
    let results: [PhotoDetailResponse]
    let limit: Int?
    let offset: Int?
    let nextOffset: Int?
}

struct MyPhotoListResponse: Codable {
    let results: [BirdmarkPhoto]
    let limit: Int?
    let offset: Int?
    let nextOffset: Int?
}

struct PhotoDetailResponse: Codable, Identifiable, Equatable {
    let photo: BirdmarkPhoto
    let observations: [BirdObservation]

    var id: Int {
        photo.id
    }
}

struct BirdmarkPhoto: Codable, Identifiable, Equatable {
    let id: Int
    let userId: Int?
    let filename: String?
    let originalPath: String?
    let thumbPath: String?
    let contentHash: String?
    let width: Int?
    let height: Int?
    let status: String?
    let errorMessage: String?
    let createdAt: String?
    let updatedAt: String?
    let deletedAt: String?
    let username: String?
    let displayName: String?
    let originalUrl: String?
    let thumbUrl: String?

    var displayTitle: String {
        filename?.isEmpty == false ? filename! : "照片 #\(id)"
    }

    var uploaderName: String {
        displayName?.isEmpty == false ? displayName! : username ?? "用户"
    }
}

struct BirdObservation: Codable, Identifiable, Equatable {
    let id: Int
    let photoId: Int?
    let cropPath: String?
    let bboxX1: Int?
    let bboxY1: Int?
    let bboxX2: Int?
    let bboxY2: Int?
    let detectionConfidence: Double?
    let detectionSource: String?
    let status: String?
    let createdAt: String?
    let updatedAt: String?
    let collectedByUserId: Int?
    let collectedAt: String?
    let deletedAt: String?
    let cropUrl: String?
    let contextUrl: String?
    let identification: Identification?

    var isCollected: Bool {
        collectedAt?.nonEmpty != nil
    }

    var canBeCollected: Bool {
        guard status != "rejected", status != "failed", let identification else {
            return false
        }
        return identification.confirmedSpeciesId != nil || (identification.topKResults?.isEmpty == false)
    }
}

struct Identification: Codable, Identifiable, Equatable {
    let id: Int?
    let observationId: Int?
    let modelName: String?
    let modelVersion: String?
    let topKResults: [Prediction]?
    let suggestedSpeciesId: Int?
    let confirmedSpeciesId: Int?
    let confirmedByUserId: Int?
    let status: String?
    let confirmedAt: String?
    let suggestedScientificName: String?
    let suggestedCommonName: String?
    let confirmedScientificName: String?
    let confirmedCommonName: String?
}

struct Prediction: Codable, Equatable {
    let scientificName: String?
    let commonName: String?
    let chineseName: String?
    let label: String?
    let score: Double?
    let confidence: Double?
    let probability: Double?
    let similarity: Double?
    let rank: Int?

    var displayName: String {
        chineseName?.nonEmpty ?? commonName?.nonEmpty ?? scientificName?.nonEmpty ?? label?.nonEmpty ?? "未知物种"
    }

    var secondaryName: String? {
        if let scientificName = scientificName?.nonEmpty, scientificName != displayName {
            return scientificName
        }
        return nil
    }

    var displayScore: String? {
        let value = score ?? confidence ?? probability ?? similarity
        guard let value else {
            return nil
        }
        return "\(Int((value * 100).rounded()))%"
    }
}

struct ConfirmObservationRequest: Encodable {
    let speciesId: Int?
    let predictionIndex: Int?
    let scientificName: String?
    let commonName: String?
    let chineseName: String?

    init(predictionIndex: Int) {
        self.speciesId = nil
        self.predictionIndex = predictionIndex
        self.scientificName = nil
        self.commonName = nil
        self.chineseName = nil
    }
}

struct ManualObservationRequest: Encodable {
    let bboxX1: Int
    let bboxY1: Int
    let bboxX2: Int
    let bboxY2: Int
    let topK: Int
}

struct ConfirmObservationResponse: Codable {
    let observation: BirdObservation
    let collectionEntry: CollectionEntry?
}

struct ObservationResponse: Codable {
    let observation: BirdObservation
}

struct CollectionListResponse: Codable {
    let results: [CollectionEntry]
}

struct CollectionEntry: Codable, Identifiable, Equatable {
    let id: Int
    let userId: Int?
    let speciesId: Int?
    let firstObservationId: Int?
    let representativeObservationId: Int?
    let representativePhotoId: Int?
    let observationCount: Int?
    let firstSeenAt: String?
    let lastSeenAt: String?
    let updatedAt: String?
    let scientificName: String?
    let commonName: String?
    let chineseName: String?
    let thumbUrl: String?
    let cropUrl: String?

    var displayName: String {
        chineseName?.nonEmpty ?? commonName?.nonEmpty ?? scientificName?.nonEmpty ?? "未知物种"
    }
}

private extension String {
    var nonEmpty: String? {
        isEmpty ? nil : self
    }
}
