import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        VStack(spacing: 30) {
            hero
            greeting
            sectionHead("01", "風格靈感", link: "瀏覽全部風格") { state.currentPage = .style }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 18) {
                    ForEach(SampleData.styles) { style in
                        StyleInspirationCard(style: style)
                            .onTapGesture {
                                state.selectedStyle = style
                                state.currentPage = .style
                            }
                    }
                }
                .padding(.vertical, 6)
            }
            sectionHead("02", "為你精選", link: "查看全部商品") { state.currentPage = .products }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                ForEach(SampleData.products.prefix(4)) { product in
                    ProductCard(product: product)
                }
            }
            about
        }
    }

    private var hero: some View {
        VStack(spacing: 0) {
            ZStack(alignment: .bottom) {
                DMColor.paper
                RadialGradient(colors: [DMColor.goldSoft.opacity(0.40), .clear], center: .top, startRadius: 10, endRadius: 250)
                VStack(spacing: 4) {
                    Text("A PLATFORM CREATED FOR THE LOVE OF BEAUTY")
                        .font(.system(size: 10.5, weight: .regular, design: .rounded))
                        .tracking(4.2)
                        .foregroundStyle(DMColor.goldDeep)
                        .padding(.top, 22)
                    Spacer(minLength: 6)
                    ZStack(alignment: .bottom) {
                        Text("DECORATE ME")
                            .font(.system(size: 70, weight: .regular, design: .serif))
                            .tracking(8)
                            .minimumScaleFactor(0.44)
                            .lineLimit(1)
                            .foregroundStyle(DMColor.gold.opacity(0.92))
                            .offset(y: -86)
                        RoundedRectangle(cornerRadius: 150, style: .continuous)
                            .fill(LinearGradient(colors: [Color(red: 0.81, green: 0.60, blue: 0.53), Color(red: 0.62, green: 0.36, blue: 0.29)], startPoint: .topLeading, endPoint: .bottomTrailing))
                            .frame(width: 224, height: 268)
                            .overlay(
                                ZStack {
                                    Circle().stroke(Color.white.opacity(0.18), lineWidth: 18).scaleEffect(1.15)
                                    Circle().stroke(Color.white.opacity(0.12), lineWidth: 1).scaleEffect(0.76)
                                    Text("裝識\n你的美")
                                        .font(.system(size: 44, weight: .regular, design: .serif))
                                        .tracking(5)
                                        .multilineTextAlignment(.center)
                                        .foregroundStyle(Color.white.opacity(0.86))
                                }
                                .clipShape(RoundedRectangle(cornerRadius: 150, style: .continuous))
                            )
                            .shadow(color: DMColor.ink.opacity(0.22), radius: 25, y: 15)
                    }
                    Spacer(minLength: 0)
                }
                Text("DASHBOARD")
                    .font(.system(size: 9, weight: .regular, design: .rounded))
                    .tracking(3.2)
                    .foregroundStyle(DMColor.goldDeep)
                    .padding(.trailing, 20)
                    .padding(.bottom, 18)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .frame(height: 348)
            .clipShape(RoundedRectangle(cornerRadius: 0, style: .continuous))

            HStack(spacing: 12) {
                Text("為你打造的美學旅程 · 從臉部分析開始")
                    .font(.system(size: 13.5, weight: .light, design: .serif))
                    .foregroundStyle(DMColor.paper)
                    .lineLimit(2)
                Spacer()
                Text("開始分析 →")
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .tracking(2.2)
                    .foregroundStyle(DMColor.goldSoft)
            }
            .padding(18)
            .background(DMColor.ink)
        }
        .contentShape(Rectangle())
        .onTapGesture { state.currentPage = .analysis }
        .shadow(color: DMColor.ink.opacity(0.13), radius: 24, y: 12)
    }

    private var greeting: some View {
        HStack(alignment: .bottom, spacing: 18) {
            VStack(alignment: .leading, spacing: 13) {
                Text("WELCOME")
                    .font(.system(size: 10.5, design: .rounded))
                    .tracking(4.2)
                    .foregroundStyle(DMColor.goldDeep)
                Text("歡迎回來，\(state.username)")
                    .font(.system(size: 31, weight: .medium, design: .serif))
                    .tracking(1.2)
                    .foregroundStyle(DMColor.ink)
                Button { state.currentPage = .analysis } label: { Text("開始臉部分析 →").dmOutlineButton() }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 6) {
                Text(Date(), style: .date)
                    .font(.system(size: 19, weight: .regular, design: .serif))
                    .italic()
                    .foregroundStyle(DMColor.goldDeep)
                Text("YOUR BEAUTY ATELIER")
                    .font(.system(size: 10, design: .rounded))
                    .tracking(2.4)
                    .foregroundStyle(DMColor.muted)
            }
        }
        .padding(.top, 2)
    }

    private func sectionHead(_ number: String, _ title: String, link: String, action: @escaping () -> Void) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(number).font(.system(size: 19, weight: .regular, design: .serif)).italic().foregroundStyle(DMColor.gold)
            Text(title).font(.system(size: 21, weight: .medium, design: .serif)).tracking(2)
            Spacer()
            Button(link, action: action)
                .font(.system(size: 10.5, weight: .medium, design: .rounded))
                .tracking(2.2)
                .foregroundStyle(DMColor.goldDeep)
        }
    }

    private var about: some View {
        HStack(spacing: 20) {
            VStack(alignment: .leading, spacing: 14) {
                Text("About the Atelier")
                    .font(.system(size: 17, design: .serif)).italic().foregroundStyle(DMColor.goldDeep)
                Text("OUR BEAUTY\nSYSTEM")
                    .font(.system(size: 35, weight: .medium, design: .serif))
                    .foregroundStyle(DMColor.ink)
                    .lineSpacing(0)
                Text("從 AI 臉部分析解讀五官與膚色，到為你量身推薦妝容風格與美妝商品。")
                    .font(.system(size: 13.5, weight: .light, design: .serif))
                    .foregroundStyle(DMColor.muted)
            }
            Spacer(minLength: 10)
            ZStack {
                RoundedRectangle(cornerRadius: 90, style: .continuous)
                    .fill(LinearGradient(colors: [DMColor.blush.opacity(0.52), DMColor.goldSoft.opacity(0.58)], startPoint: .top, endPoint: .bottom))
                Text("❧")
                    .font(.system(size: 66, design: .serif))
                    .foregroundStyle(Color.white.opacity(0.78))
            }
            .frame(width: 118, height: 174)
        }
        .padding(24)
        .background(DMColor.paper.opacity(0.92), in: RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 28).stroke(.white.opacity(0.55), lineWidth: 1))
    }
}

struct StyleInspirationCard: View {
    let style: MakeupStyle
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            Image(style.imageName)
                .resizable()
                .scaledToFill()
                .frame(width: 216, height: 238)
                .clipped()
                .overlay(alignment: .topLeading) {
                    Text("✦")
                        .font(.title3)
                        .padding(12)
                        .foregroundStyle(DMColor.goldDeep)
                }
                .overlay(alignment: .bottomLeading) {
                    LinearGradient(colors: [.clear, DMColor.ink.opacity(0.42)], startPoint: .top, endPoint: .bottom)
                        .frame(height: 88)
                }
            VStack(alignment: .leading, spacing: 7) {
                Text(style.name)
                    .font(.system(size: 21, weight: .medium, design: .serif))
                    .foregroundStyle(DMColor.ink)
                Text(style.tags.prefix(2).joined(separator: " · "))
                    .font(.system(size: 10.5, design: .rounded))
                    .tracking(1.5)
                    .foregroundStyle(DMColor.goldDeep)
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 15)
        }
        .frame(width: 216)
        .background(.white.opacity(0.34), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(Color.white.opacity(0.58), lineWidth: 1))
        .shadow(color: DMColor.ink.opacity(0.07), radius: 16, y: 8)
    }
}

struct AnalysisView: View {
    @EnvironmentObject private var state: AppState
    @State private var mode = "BASIC"
    var body: some View {
        VStack(spacing: 24) {
            PageHeader(eyebrow: "Face Analysis", title: "臉部分析", subtitle: "上傳正面照片或使用示範分析，AI 為你分析五官特徵。")
            HStack(spacing: 10) {
                modeButton("BASIC")
                modeButton("PRO")
            }
            VStack(spacing: 18) {
                ZStack {
                    RoundedRectangle(cornerRadius: 28, style: .continuous)
                        .fill(DMColor.paper)
                        .overlay(RoundedRectangle(cornerRadius: 28).stroke(DMColor.gold.opacity(0.35), style: StrokeStyle(lineWidth: 1, dash: [6, 6])))
                    VStack(spacing: 16) {
                        Text("＋")
                            .font(.system(size: 32, weight: .light, design: .serif))
                            .foregroundStyle(DMColor.gold)
                            .frame(width: 58, height: 58)
                            .overlay(RoundedRectangle(cornerRadius: 18).stroke(DMColor.gold.opacity(0.35), lineWidth: 1))
                        Text(mode == "BASIC" ? "選擇正面照片" : "正面照 + 側面照")
                            .font(.system(size: 17, weight: .medium, design: .serif))
                        Text("正式版可接 PhotosPicker / Camera，示範版先使用 Mock API 流程。")
                            .font(.system(size: 12, design: .serif))
                            .multilineTextAlignment(.center)
                            .foregroundStyle(DMColor.muted)
                    }
                    .padding(30)
                }
                .frame(height: 240)
                if state.isAnalyzing {
                    ProgressView(value: state.analysisProgress)
                        .tint(DMColor.gold)
                    Text(state.package?.status ?? "processing")
                        .font(.system(size: 12, design: .rounded))
                        .tracking(2)
                        .foregroundStyle(DMColor.goldDeep)
                }
                Button { state.runDemoAnalysis(mode: mode) } label: { Text("開始分析").dmPrimaryButton() }
            }
            resultPanel
        }
    }

    private func modeButton(_ value: String) -> some View {
        Button { mode = value } label: {
            Text(value)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .tracking(2)
                .foregroundStyle(mode == value ? DMColor.ink : DMColor.goldDeep)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(mode == value ? DMColor.goldSoft.opacity(0.7) : Color.white.opacity(0.3), in: Capsule())
        }
    }

    private var resultPanel: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("分析結果")
                .font(.system(size: 20, weight: .medium, design: .serif))
            let r = state.latestAnalysis
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                ResultCell(label: "臉型", value: r?.faceShape ?? "—")
                ResultCell(label: "眉型", value: r?.browShape ?? "—")
                ResultCell(label: "眼型", value: r?.eyeShape ?? "—")
                ResultCell(label: "鼻型", value: r?.noseShape ?? "—")
                ResultCell(label: "嘴型", value: r?.lipShape ?? "—")
                ResultCell(label: "膚色", value: r?.skinTone ?? "—")
            }
        }
        .padding(18)
        .background(DMColor.paper, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

struct ResultCell: View {
    let label: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.system(size: 10, design: .rounded)).tracking(2).foregroundStyle(DMColor.goldDeep)
            Text(value).font(.system(size: 18, weight: .medium, design: .serif)).foregroundStyle(DMColor.ink)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.white.opacity(0.36), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

struct StyleView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Style Atelier", title: "風格試妝", subtitle: "選擇一種妝容風格，為你量身打造妝容建議。")
            LazyVStack(spacing: 16) {
                ForEach(SampleData.styles) { style in
                    StyleDetailCard(style: style, selected: state.selectedStyle == style)
                        .onTapGesture { state.selectedStyle = style }
                }
            }
            Button { state.generateSuggestion() } label: { Text("確認風格 →").dmPrimaryButton() }
        }
    }
}

struct StyleDetailCard: View {
    let style: MakeupStyle
    let selected: Bool
    var body: some View {
        HStack(spacing: 16) {
            Image(style.imageName)
                .resizable()
                .scaledToFill()
                .frame(width: 116, height: 150)
                .clipped()
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            VStack(alignment: .leading, spacing: 9) {
                HStack {
                    Text(style.name).font(.system(size: 22, weight: .medium, design: .serif))
                    Spacer()
                    if selected { Image(systemName: "checkmark.seal.fill").foregroundStyle(DMColor.goldDeep) }
                }
                Text(style.intro).font(.system(size: 12, design: .serif)).foregroundStyle(DMColor.muted).lineLimit(3)
                HStack {
                    ForEach(style.palette.indices, id: \.self) { i in Circle().fill(style.palette[i]).frame(width: 18, height: 18) }
                }
                TagRow(tags: style.tags.prefix(3).map { $0 })
            }
        }
        .padding(14)
        .background(selected ? DMColor.paper : Color.white.opacity(0.30), in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 26).stroke(selected ? DMColor.gold : Color.white.opacity(0.45), lineWidth: 1))
    }
}

struct ProductsView: View {
    @EnvironmentObject private var state: AppState
    let columns = [GridItem(.flexible()), GridItem(.flexible())]
    var categories: [String] { ["全部"] + Array(Set(SampleData.products.map(\.category))).sorted() }
    var products: [BeautyProduct] {
        if let c = state.selectedCategory, c != "全部" { return SampleData.products.filter { $0.category == c } }
        return SampleData.products
    }
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Products", title: "商品推薦", subtitle: "依照妝容風格與臉部分析推薦適合你的美妝品。")
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(categories, id: \.self) { cat in
                        Button { state.selectedCategory = cat } label: {
                            Text(cat)
                                .font(.system(size: 13, design: .serif))
                                .foregroundStyle((state.selectedCategory ?? "全部") == cat ? DMColor.ink : DMColor.goldDeep)
                                .padding(.horizontal, 16).padding(.vertical, 10)
                                .background((state.selectedCategory ?? "全部") == cat ? DMColor.goldSoft.opacity(0.55) : Color.white.opacity(0.3), in: Capsule())
                        }
                    }
                }
            }
            LazyVGrid(columns: columns, spacing: 16) {
                ForEach(products) { product in ProductCard(product: product) }
            }
        }
    }
}

struct ProductCard: View {
    @EnvironmentObject private var state: AppState
    let product: BeautyProduct
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            ZStack {
                RoundedRectangle(cornerRadius: 22).fill(LinearGradient(colors: [DMColor.paper, .white.opacity(0.55)], startPoint: .top, endPoint: .bottom))
                Text(product.category.prefix(1))
                    .font(.system(size: 42, design: .serif))
                    .foregroundStyle(DMColor.gold.opacity(0.55))
            }
            .frame(height: 150)
            Text(product.category).font(.system(size: 9, design: .rounded)).tracking(2).foregroundStyle(DMColor.goldDeep)
            Text(product.name).font(.system(size: 16, weight: .medium, design: .serif)).foregroundStyle(DMColor.ink)
            Text(product.price).font(.system(size: 13, weight: .medium, design: .rounded)).foregroundStyle(DMColor.goldDeep)
            HStack {
                Button { state.toggleFavorite(product) } label: {
                    Image(systemName: state.favoriteProductIDs.contains(product.id) ? "heart.fill" : "heart")
                        .foregroundStyle(DMColor.goldDeep)
                        .frame(width: 36, height: 36)
                        .background(.white.opacity(0.35), in: Circle())
                }
                Button { state.addToCart(product) } label: {
                    Text("加入")
                        .font(.system(size: 11, weight: .medium, design: .rounded))
                        .foregroundStyle(DMColor.ink)
                        .frame(maxWidth: .infinity)
                        .frame(height: 36)
                        .background(DMColor.goldSoft.opacity(0.75), in: Capsule())
                }
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.28), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

struct FavoritesView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Wishlist", title: "我的收藏", subtitle: "儲存你喜歡的商品。")
            if state.favorites.isEmpty { EmptyState(text: "目前還沒有收藏商品") }
            else { ForEach(state.favorites) { ProductCard(product: $0) } }
        }
    }
}

struct HistoryView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Archive", title: "分析紀錄", subtitle: "查看過去的臉部分析結果。")
            if state.analysisHistory.isEmpty { EmptyState(text: "尚未建立分析紀錄") }
            else {
                ForEach(state.analysisHistory) { item in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(item.date, style: .date).font(.system(size: 12, design: .rounded)).foregroundStyle(DMColor.goldDeep)
                        HStack { ResultCell(label: "模式", value: item.mode); ResultCell(label: "臉型", value: item.faceShape) }
                        HStack { ResultCell(label: "眼型", value: item.eyeShape); ResultCell(label: "膚色", value: item.skinTone) }
                    }
                    .padding(16).background(DMColor.paper, in: RoundedRectangle(cornerRadius: 24))
                }
            }
        }
    }
}

struct CompareView: View {
    @EnvironmentObject private var state: AppState
    @State private var showAfter = false
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Before / After", title: "妝容對比圖", subtitle: "按住切換渲染前 / 渲染後效果。")
            ZStack(alignment: .bottom) {
                Image((state.selectedStyle ?? SampleData.styles[1]).imageName)
                    .resizable().scaledToFill().frame(height: 420).clipped()
                    .saturation(showAfter ? 1.1 : 0.25)
                    .brightness(showAfter ? 0.02 : -0.04)
                    .overlay(showAfter ? Color.clear : Color.white.opacity(0.25))
                Text(showAfter ? "渲染後 · \((state.selectedStyle ?? SampleData.styles[1]).name)" : "渲染前照片")
                    .font(.system(size: 12, weight: .medium, design: .rounded)).tracking(2)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(.black.opacity(0.35), in: Capsule())
                    .padding(18)
            }
            .clipShape(RoundedRectangle(cornerRadius: 30, style: .continuous))
            Button {} label: { Text("按住對比") .dmPrimaryButton() }
                .simultaneousGesture(DragGesture(minimumDistance: 0).onChanged { _ in showAfter = true }.onEnded { _ in showAfter = false })
            Button { if let style = state.selectedStyle { state.savedLooks.insert(SavedLook(date: Date(), style: style, analysis: state.latestAnalysis), at: 0) } } label: { Text("收藏妝容對比圖").dmOutlineButton() }
        }
    }
}

struct SuggestionView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Suggestion", title: "妝容建議", subtitle: "依照臉部分析結果與選擇風格，產生完整建議。")
            if let style = state.selectedStyle {
                StyleDetailCard(style: style, selected: true)
                AdviceGrid(style: style)
                Button { state.currentPage = .compare } label: { Text("查看妝容對比圖 →").dmPrimaryButton() }
            } else {
                EmptyState(text: "尚未選擇妝容風格")
            }
        }
    }
}

struct AdviceGrid: View {
    let style: MakeupStyle
    var body: some View {
        VStack(spacing: 12) {
            AdviceCell(title: "底妝", text: style.advice.base)
            AdviceCell(title: "眉型", text: style.advice.brow)
            AdviceCell(title: "眼妝", text: style.advice.eye)
            AdviceCell(title: "腮紅 / 修容", text: style.advice.blush)
            AdviceCell(title: "唇妝", text: style.advice.lip)
        }
    }
}

struct AdviceCell: View {
    let title: String
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.system(size: 12, weight: .medium, design: .rounded)).tracking(2).foregroundStyle(DMColor.goldDeep)
            Text(text).font(.system(size: 14, design: .serif)).foregroundStyle(DMColor.ink)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(DMColor.paper, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

struct ProfileView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        VStack(spacing: 22) {
            PageHeader(eyebrow: "Member", title: "會員中心", subtitle: "查看會員資料、分析次數與收藏妝容。")
            VStack(spacing: 14) {
                Text("✦").font(.system(size: 42)).foregroundStyle(DMColor.goldDeep).frame(width: 92, height: 92).background(DMColor.paper, in: Circle())
                Text(state.username).font(.system(size: 24, weight: .medium, design: .serif))
                Text(state.isGuest ? "訪客模式" : "Decorate Me Member").font(.system(size: 11, design: .rounded)).tracking(2).foregroundStyle(DMColor.goldDeep)
            }
            HStack {
                StatCell(title: "Wishlist", number: state.favorites.count, label: "收藏商品")
                StatCell(title: "Analysis", number: state.analysisHistory.count, label: "分析次數")
                StatCell(title: "Looks", number: state.savedLooks.count, label: "收藏妝容")
            }
            if state.savedLooks.isEmpty { EmptyState(text: "尚未收藏妝容對比圖") }
            else {
                ForEach(state.savedLooks) { look in
                    HStack(spacing: 14) {
                        Image(look.style.imageName).resizable().scaledToFill().frame(width: 78, height: 94).clipped().clipShape(RoundedRectangle(cornerRadius: 14))
                        VStack(alignment: .leading, spacing: 5) {
                            Text(look.style.name).font(.system(size: 18, weight: .medium, design: .serif))
                            Text(look.date, style: .date).font(.caption).foregroundStyle(DMColor.muted)
                        }
                        Spacer()
                    }
                    .padding(12).background(DMColor.paper, in: RoundedRectangle(cornerRadius: 20))
                }
            }
            Button { state.logout() } label: { Text("Sign Out").dmOutlineButton() }
        }
    }
}

struct StatCell: View {
    let title: String
    let number: Int
    let label: String
    var body: some View {
        VStack(spacing: 6) {
            Text(title).font(.system(size: 9, design: .rounded)).tracking(1.4).foregroundStyle(DMColor.goldDeep)
            Text("\(number)").font(.system(size: 24, weight: .medium, design: .serif)).foregroundStyle(DMColor.ink)
            Text(label).font(.system(size: 11, design: .serif)).foregroundStyle(DMColor.muted)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 14).background(DMColor.paper, in: RoundedRectangle(cornerRadius: 20))
    }
}

struct TagRow: View {
    let tags: [String]
    var body: some View {
        FlowLayout(spacing: 6) {
            ForEach(tags, id: \.self) { tag in
                Text(tag).font(.system(size: 10, design: .serif)).foregroundStyle(DMColor.goldDeep).padding(.horizontal, 9).padding(.vertical, 5).background(.white.opacity(0.38), in: Capsule())
            }
        }
    }
}

struct EmptyState: View {
    let text: String
    var body: some View {
        VStack(spacing: 12) {
            Text("❧").font(.system(size: 52, design: .serif)).foregroundStyle(DMColor.gold.opacity(0.5))
            Text(text).font(.system(size: 15, design: .serif)).foregroundStyle(DMColor.muted)
        }.frame(maxWidth: .infinity).padding(44).background(DMColor.paper, in: RoundedRectangle(cornerRadius: 24))
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? 320
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > maxWidth { x = 0; y += lineHeight + spacing; lineHeight = 0 }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
        return CGSize(width: maxWidth, height: y + lineHeight)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX { x = bounds.minX; y += lineHeight + spacing; lineHeight = 0 }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}
