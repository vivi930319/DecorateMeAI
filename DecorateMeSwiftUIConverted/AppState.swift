import SwiftUI
import Foundation

final class AppState: ObservableObject {
    @Published var isLoggedIn: Bool = false
    @Published var username: String = "訪客"
    @Published var isGuest: Bool = true
    @Published var currentPage: AppPage = .dashboard
    @Published var selectedStyle: MakeupStyle? = SampleData.styles.first
    @Published var selectedCategory: String? = nil
    @Published var favoriteProductIDs: Set<Int> = []
    @Published var cart: [Int: Int] = [:]
    @Published var analysisHistory: [AnalysisResult] = []
    @Published var savedLooks: [SavedLook] = []
    @Published var package: AnalysisPackage? = nil
    @Published var isAnalyzing: Bool = false
    @Published var analysisProgress: Double = 0

    var favorites: [BeautyProduct] {
        SampleData.products.filter { favoriteProductIDs.contains($0.id) }
    }

    var cartCount: Int { cart.values.reduce(0, +) }

    var latestAnalysis: AnalysisResult? { analysisHistory.first }

    func login(name: String, guest: Bool) {
        username = name.isEmpty ? "訪客" : name
        isGuest = guest
        isLoggedIn = true
        currentPage = .dashboard
    }

    func logout() {
        isLoggedIn = false
        username = "訪客"
        isGuest = true
        currentPage = .dashboard
    }

    func toggleFavorite(_ product: BeautyProduct) {
        if favoriteProductIDs.contains(product.id) { favoriteProductIDs.remove(product.id) }
        else { favoriteProductIDs.insert(product.id) }
    }

    func addToCart(_ product: BeautyProduct) {
        cart[product.id, default: 0] += 1
    }

    func runDemoAnalysis(mode: String = "BASIC") {
        isAnalyzing = true
        analysisProgress = 0.12
        package = AnalysisPackage(id: "AN-\(Int(Date().timeIntervalSince1970))", schemaVersion: "2026-06-v1", mode: mode, status: "queued", faceAnalysis: nil, selectedStyleId: selectedStyle?.id, suggestion: nil, progress: analysisProgress)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) { [weak self] in
            self?.analysisProgress = 0.45
            self?.package?.status = "processing"
            self?.package?.progress = 0.45
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.25) { [weak self] in
            guard let self else { return }
            let result = AnalysisResult(date: Date(), faceShape: "鵝蛋臉", browShape: "彎月眉", eyeShape: "桃花眼", noseShape: "標準鼻", lipShape: "微笑唇", skinTone: "Spring 白皙", mode: mode)
            self.analysisHistory.insert(result, at: 0)
            self.analysisProgress = 1
            self.isAnalyzing = false
            self.package?.status = "completed"
            self.package?.faceAnalysis = result
            self.package?.progress = 1
            self.currentPage = .style
        }
    }

    func generateSuggestion() {
        guard let style = selectedStyle else { return }
        var text = "依照目前臉部分析，建議使用 \(style.name) 妝容。\n\n"
        text += "底妝：\(style.advice.base)\n眉型：\(style.advice.brow)\n眼妝：\(style.advice.eye)\n腮紅：\(style.advice.blush)\n唇妝：\(style.advice.lip)"
        package?.suggestion = text
        package?.selectedStyleId = style.id
        savedLooks.insert(SavedLook(date: Date(), style: style, analysis: latestAnalysis), at: 0)
        currentPage = .suggestion
    }
}
