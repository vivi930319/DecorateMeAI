import SwiftUI
import Foundation

enum AppPage: String, CaseIterable, Identifiable {
    case dashboard = "首頁"
    case analysis = "臉部分析"
    case style = "風格試妝"
    case products = "商品推薦"
    case favorites = "收藏"
    case history = "分析紀錄"
    case compare = "妝容對比圖"
    case suggestion = "妝容建議"
    case profile = "會員中心"
    var id: String { rawValue }
    var english: String {
        switch self {
        case .dashboard: return "Dashboard"
        case .analysis: return "Face Analysis"
        case .style: return "Style Atelier"
        case .products: return "Products"
        case .favorites: return "Wishlist"
        case .history: return "Archive"
        case .compare: return "Before / After"
        case .suggestion: return "Suggestion"
        case .profile: return "Member"
        }
    }
}

struct MakeupAdvice: Hashable {
    let base: String
    let brow: String
    let eye: String
    let blush: String
    let lip: String
}

struct MakeupStyle: Identifiable, Hashable {
    let id: String
    let name: String
    let imageName: String
    let tags: [String]
    let intro: String
    let palette: [Color]
    let advice: MakeupAdvice
}

struct BeautyProduct: Identifiable, Hashable {
    let id: Int
    let category: String
    let name: String
    let price: String
    let description: String
}

struct AnalysisResult: Identifiable, Hashable {
    let id = UUID()
    let date: Date
    let faceShape: String
    let browShape: String
    let eyeShape: String
    let noseShape: String
    let lipShape: String
    let skinTone: String
    let mode: String
}

struct SavedLook: Identifiable, Hashable {
    let id = UUID()
    let date: Date
    let style: MakeupStyle
    let analysis: AnalysisResult?
}

struct AnalysisPackage: Identifiable, Hashable {
    let id: String
    let schemaVersion: String
    let mode: String
    var status: String
    var faceAnalysis: AnalysisResult?
    var selectedStyleId: String?
    var suggestion: String?
    var progress: Double
}

enum SampleData {
    static let styles: [MakeupStyle] = [
        MakeupStyle(
            id: "softBaddie", name: "Soft Baddie", imageName: "koreanClean",
            tags: ["柔霧底妝", "甜酷氛圍", "自然修容", "微性感"],
            intro: "柔霧底妝搭配甜酷眼唇重點，保留精緻感又帶一點攻擊性的妝容。",
            palette: [Color(red: 0.85, green: 0.71, blue: 0.62), Color(red: 0.73, green: 0.47, blue: 0.44), Color(red: 0.49, green: 0.33, blue: 0.29)],
            advice: MakeupAdvice(base: "清透柔霧底妝，局部遮瑕保留自然膚質。", brow: "眉峰略拉高，保留俐落毛流。", eye: "柔霧大地色加深眼尾，眼線略拉長。", blush: "腮紅位置偏高，搭配輕微修容。", lip: "低飽和玫瑰或肉桂色，邊界微霧化。")
        ),
        MakeupStyle(
            id: "richGirl", name: "千金", imageName: "richGirl",
            tags: ["高級感", "精緻底妝", "低調奢華", "氣質妝容"],
            intro: "乾淨底妝、低飽和色彩與細節光澤，精緻但不厚重。",
            palette: [Color(red: 0.91, green: 0.80, blue: 0.73), Color(red: 0.80, green: 0.64, blue: 0.52), Color(red: 0.65, green: 0.49, blue: 0.41)],
            advice: MakeupAdvice(base: "薄透光澤底妝，重點放在膚色均勻。", brow: "順著原生眉型補空隙，避免過重。", eye: "燕麥、奶茶色眼影，眼頭少量提亮。", blush: "低飽和裸粉或杏色，淡淡掃在蘋果肌。", lip: "奶茶玫瑰、裸豆沙色最穩。")
        ),
        MakeupStyle(
            id: "hongKong", name: "港風", imageName: "hongKong",
            tags: ["復古感", "濃郁五官", "氛圍唇色", "立體眉眼"],
            intro: "復古港風重點是濃郁眉眼與飽和唇色，適合強化五官。",
            palette: [Color(red: 0.72, green: 0.36, blue: 0.30), Color(red: 0.49, green: 0.18, blue: 0.16), Color(red: 0.78, green: 0.61, blue: 0.43)],
            advice: MakeupAdvice(base: "霧面底妝搭配明確輪廓。", brow: "眉型可稍粗，保留自然眉峰。", eye: "暖棕大面積暈染，內眼線強化眼神。", blush: "偏暖磚紅或杏棕，連接修容。", lip: "復古紅、磚紅、濃郁玫瑰色。")
        ),
        MakeupStyle(
            id: "koreanClean", name: "韓系亞裔", imageName: "koreanClean",
            tags: ["清透感", "偽素顏", "低飽和", "日常自然"],
            intro: "乾淨透明、低負擔的日常妝感，重點在膚質與淡色層次。",
            palette: [Color(red: 0.95, green: 0.79, blue: 0.77), Color(red: 0.90, green: 0.69, blue: 0.66), Color(red: 0.85, green: 0.75, blue: 0.66)],
            advice: MakeupAdvice(base: "保濕氣墊或輕薄粉底，保留自然光澤。", brow: "平柔眉或自然野生眉，顏色比髮色淺。", eye: "粉裸、米棕消腫，臥蠶自然提亮。", blush: "蜜桃粉或淡杏色，範圍小而柔。", lip: "水光唇釉、粉裸色或 MLBB。")
        ),
        MakeupStyle(
            id: "yandere", name: "病嬌", imageName: "yandere",
            tags: ["白皙氛圍", "眼下腮紅", "微病感", "角色感"],
            intro: "白皙底妝、眼下腮紅與血色唇，營造脆弱角色氛圍。",
            palette: [Color(red: 0.91, green: 0.63, blue: 0.65), Color(red: 0.72, green: 0.29, blue: 0.36), Color(red: 0.95, green: 0.85, blue: 0.85)],
            advice: MakeupAdvice(base: "底妝可比平常略亮，但避免灰白。", brow: "眉色淡化，降低攻擊感。", eye: "眼下粉紅暈染，眼線微下垂。", blush: "腮紅集中眼下到顴骨上方。", lip: "咬唇、血色紅或莓果色。")
        ),
        MakeupStyle(
            id: "japaneseClear", name: "日雜清透", imageName: "japaneseClear",
            tags: ["透明感", "柔和自然", "淡色系", "溫柔日常"],
            intro: "空氣感、柔霧與淡色層次，自然但有細節的日系妝容。",
            palette: [Color(red: 0.94, green: 0.72, blue: 0.66), Color(red: 0.89, green: 0.65, blue: 0.55), Color(red: 0.84, green: 0.71, blue: 0.64)],
            advice: MakeupAdvice(base: "輕薄霧光底妝，局部定妝。", brow: "淡眉色與柔和眉尾。", eye: "單色蜜桃或淡棕眼影，少量珠光。", blush: "淡粉橘橫向暈染，營造親和感。", lip: "潤澤珊瑚、透明紅或蜜桃色。")
        ),
        MakeupStyle(
            id: "mensPlain", name: "男士白開水", imageName: "mensPlain",
            tags: ["乾淨自然", "原生質感", "清爽眉眼", "低妝感"],
            intro: "保留男性原生輪廓與肌膚質感，以輕薄修飾呈現清爽白開水妝。",
            palette: [Color(red: 0.90, green: 0.85, blue: 0.81), Color(red: 0.75, green: 0.66, blue: 0.60), Color(red: 0.50, green: 0.44, blue: 0.40)],
            advice: MakeupAdvice(base: "局部遮瑕並薄透均勻膚色，保留自然肌理。", brow: "順著原生眉流補齊空隙，眉尾俐落不描框。", eye: "霧面淺棕輕掃眼窩與下眼尾。", blush: "低飽和裸杏色少量修飾氣色，也可省略。", lip: "透明護唇或低彩度裸豆沙色。")
        )
    ]

    static let products: [BeautyProduct] = [
        BeautyProduct(id: 1, category: "底妝", name: "柔光粉嫩粉底", price: "NT$980", description: "打造乾淨柔霧底妝，保留自然光澤。"),
        BeautyProduct(id: 2, category: "底妝", name: "玫瑰金妝前乳", price: "NT$760", description: "修飾毛孔與膚色，讓底妝更貼。"),
        BeautyProduct(id: 3, category: "眼影", name: "咖卡大地眼影盤", price: "NT$1,280", description: "日常與港風妝感都適用。"),
        BeautyProduct(id: 4, category: "眼線/睫毛", name: "細緻防暈眼線液", price: "NT$520", description: "線條俐落，放大眼神。"),
        BeautyProduct(id: 5, category: "唇彩", name: "奶茶保濕唇釉", price: "NT$620", description: "低飽和氣質色，自然不突兀。"),
        BeautyProduct(id: 6, category: "腮紅", name: "玫瑰奶茶腮紅", price: "NT$590", description: "自然血色與精緻氛圍。"),
        BeautyProduct(id: 7, category: "眉毛彩妝", name: "柔霧眉粉盤", price: "NT$480", description: "調整眉色，讓五官更柔和。"),
        BeautyProduct(id: 8, category: "修容", name: "冷棕修容棒", price: "NT$690", description: "修飾臉型輪廓。"),
        BeautyProduct(id: 9, category: "打亮", name: "細閃香檳打亮", price: "NT$720", description: "提升肌膚精緻光澤。")
    ]
}
