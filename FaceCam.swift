//  FaceCam_AllInOne_NoMain_Fixed.swift
//  FaceCam
//  上半部80%相機畫面, 下半部20%快門 ,文字提示
import SwiftUI
//UI 框架
import AVFoundation
//相機,影音相關 API
import UIKit
//UIImage 需要 UIKit
import Combine
//ObservableObject,@Published 需要 Combine

// MARK: - 主畫面
struct ContentView: View {
    //主畫面 SwiftUI View 宣告
    @StateObject private var cameraManager = CameraManager()   //相機管理器（生命週期綁定在 View）
    @State private var capturedImage: UIImage? = nil               //保存拍到的照片（UIImage）
    @State private var showPreviewSheet = false
    //控制是否彈出預覽 Sheet
    private let warningText = "請在光源充足的場所拍攝清晰全臉"          //左側直列提醒內容（之後會被拆成逐字直排）
    var body: some View {
        //SwiftUI 介面進入點
        GeometryReader { geo in
            //取得螢幕尺寸,用來做 8:2 高度比例
            VStack(spacing: 0) {
                //垂直堆疊（上相機/下快門區）
                ZStack(alignment: .topLeading) {                   //疊加容器（相機畫面當底，文字/遮罩疊上去）
                    CameraPreview(session: cameraManager.session)
                    //把 AVCaptureSession 接到 SwiftUI
                        .ignoresSafeArea()
                    //相機畫面延伸到安全區外（滿版）
                    VStack(alignment: .center, spacing: 10) {
                        //垂直排列：警告圖示在上、文字在下
                        Image(systemName: "exclamationmark.triangle.fill")
                        //警告三角形 SF Symbol
                            .font(.system(size: 18, weight: .bold))
                        //設定圖示大小與粗細
                            .foregroundColor(.yellow)
                        //圖示顏色為黃色
                        Text(verticalString(warningText))
                        //將句子拆成每個字換行，形成直排
                            .font(.system(size: 18, weight: .semibold))
                        //文字大小與字重
                            .foregroundColor(.black)
                        //文字顏色
                            .multilineTextAlignment(.center)
                        //多行文字置中
                            .lineSpacing(4)
                        //調整每行（每字）之間的距離
                    }
                    .padding(.top, 18)
                    //與上方留白,固定在上半部
                    .padding(.leading, 14)
                    //與左側留白,貼齊左邊但不貼邊
                    if let msg = cameraManager.overlayMessage {
                        //有訊息時才顯示（nil 表示正常）
                        statusOverlay(msg)
                        //呼叫下方的 statusOverlay 產生遮罩 View
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center) //置中覆蓋整個上半部
                    }
                }
                .frame(height: geo.size.height * 0.80)
                //上半部高度 = 螢幕 80%（8:2）
                ZStack {
                    Color(red: 0.55, green: 0.48, blue: 0.40)
                    //咖啡色背景
                        .ignoresSafeArea()
                    //延伸到底部安全區
                    Button {
                        //快門按鈕
                        cameraManager.takePhoto { img in
                            //呼叫相機管理器拍照,回傳 UIImage
                            self.capturedImage = img
                            //保存照片到狀態,供預覽使用
                            self.showPreviewSheet = (img != nil)
                            //有照片才開啟預覽 Sheet
                        }
                    } label: {
                        //按鈕外觀
                        ZStack {
                            //兩個圓疊加做出快門樣式
                            Circle()
                                .stroke(Color.white, lineWidth: 8)
                            //白色描邊外圈
                                .frame(width: 92, height: 92)
                            //外圈大小
                            Circle()
                                .fill(Color.white.opacity(0.18))
                            //白色半透明填滿
                                .frame(width: 74, height: 74)
                            //內圈大小
                        }
                    }
                }
                .frame(height: geo.size.height * 0.20)
                //下半部高度 = 螢幕 20%（8:2）
            }
            .onAppear { cameraManager.start() }
            //畫面出現時啟動相機 session
            .onDisappear { cameraManager.stop() }
            //畫面離開時停止 session
            .sheet(isPresented: $showPreviewSheet) {
                //拍到照片後彈出預覽頁
                PhotoPreviewView(image: capturedImage)
                //把拍到的照片傳入預覽 View
            }
        }
    }
    private func verticalString(_ s: String) -> String {
        //將整句拆成逐字換行
        s.map { String($0) }.joined(separator: "\n")               //每個字元轉成字串,再用換行串起來
    }
    private func statusOverlay(_ msg: String) -> some View {       //傳入訊息字串,回傳一個 SwiftUI View
        VStack(spacing: 12) {
            //垂直排列 loading 與文字
            ProgressView()
            //系統預設的 loading 指示器
            Text(msg)
            //顯示狀態訊息
                .font(.headline)
            //字體樣式
                .foregroundColor(.white)
            //白字搭配黑底
                .multilineTextAlignment(.center)
            //多行置中
                .padding(.horizontal, 18)
            //左右留白
        }
        .padding(.vertical, 18)
        //上下內距
        .padding(.horizontal, 16)
        //左右內距
        .background(Color.black.opacity(0.55))
        //半透明黑底
        .clipShape(RoundedRectangle(cornerRadius: 18))
        //圓角框
        .padding()
        //外距,避免貼邊
    }
}
// MARK: - 拍照預覽
struct PhotoPreviewView: View {
    let image: UIImage?
    //外部傳入的照片（可為 nil）
    var body: some View {
        //預覽頁 UI
        NavigationView {
            //用導覽列包住,顯示標題
            Group {
                //群組容器,用於條件顯示
                if let img = image {
                    //有照片就顯示照片
                    Image(uiImage: img)
                    //把 UIImage 轉成 SwiftUI Image
                        .resizable()
                    //允許縮放
                        .scaledToFit()
                    //等比縮放完整顯示
                        .padding()
                    //留白
                } else {
                    //沒有照片就顯示文字
                    Text("沒有照片")
                    //提示使用者沒有成功拍到
                        .foregroundColor(.secondary)
                }
            }
            .navigationTitle("拍照預覽")
            //導覽列標題
            .navigationBarTitleDisplayMode(.inline)
            //標題顯示模式
        }
    }
}
// MARK: - 相機管理
final class CameraManager: NSObject, ObservableObject {            //ObservableObject 讓 SwiftUI 監聽狀態
    @Published private(set) var session = AVCaptureSession()
    //相機 Session（給預覽層用,外部只讀）
    @Published var overlayMessage: String? = "啟動相機中…"
    //上半部遮罩訊息（nil 表示不顯示）
    private let sessionQueue = DispatchQueue(label: "camera.session.queue") //相機操作專用序列 queue（避免卡 UI）
    private var isConfigured = false
    //避免重複配置 session
    private let photoOutput = AVCapturePhotoOutput()               //備註：拍照輸出（AVCapturePhotoOutput）
    private var currentDelegate: PhotoCaptureDelegate?
    //強引用 delegate,避免拍照回呼消失
    func start() {
        //啟動相機（請求權限→配置→startRunning）
#if targetEnvironment(simulator)                                   //如果是模擬器環境
        overlayMessage = "模擬器沒有相機\n請用真機測試"
        //模擬器無相機，顯示提示
        return
#else                                                              //真機環境
        Task {
            //使用 async/await 流程（請求權限）
            let ok = await requestPermission()
            //請求相機權限,回傳是否允許
            if !ok {
                //若未授權
                await MainActor.run {
                    //回到主執行緒更新 UI
                    self.overlayMessage = "未取得相機權限\n請到 設定 → FaceCam → 相機 開啟" //提示去設定開權限
                }
                return
            }
            sessionQueue.async {
                //在相機專用 queue 做配置與 startRunning
                if !self.isConfigured {
                    //尚未配置才配置
                    self.configureSession()
                    //建立 input/output 等
                }
                if self.isConfigured && !self.session.isRunning {  //已配置且還沒跑才啟動 session
                    self.session.startRunning()
                    //開始相機串流
                }
                Task { @MainActor in
                    //回到主執行緒更新遮罩訊息
                    self.overlayMessage = self.session.isRunning ? nil : "相機尚未啟動" //跑起來就隱藏遮罩
                }
            }
        }
#endif                                                             //條件編譯結束
    }
    func stop() {
        //停止相機（離開畫面時呼叫）
        sessionQueue.async {
            //在相機 queue 停止,避免競態
            if self.session.isRunning { self.session.stopRunning() } //若正在跑就停止
            Task { @MainActor in self.overlayMessage = nil }
            //回到主執行緒清除遮罩訊息
        }
    }
    func takePhoto(onPhoto: @escaping (UIImage?) -> Void) {
        //拍照函式,回傳 UIImage?
        sessionQueue.async {
            //在相機 queue 進行拍照動作
            if !self.isConfigured { self.configureSession() }
            //若尚未配置就先配置
            if self.isConfigured && !self.session.isRunning { self.session.startRunning() }
            //確保 session 正在跑
            guard self.session.isRunning else {
                //若仍沒跑起來
                Task { @MainActor in
                    //回主執行緒提示
                    self.overlayMessage = "無法啟動相機\n請確認未被其他 App 佔用" //常見原因:被別的 App 佔用
                }
                onPhoto(nil)
                //回傳 nil 表示失敗
                return
            }
            let settings = AVCapturePhotoSettings()
            //建立拍照設定
            settings.flashMode = .off
            //關閉閃光燈（前鏡頭通常也用不到）
            let delegate = PhotoCaptureDelegate { image in
                //建立拍照回呼 delegate
                onPhoto(image)
                //把拍到的照片往外回傳
            }
            self.currentDelegate = delegate
            //強引用,避免 delegate 被釋放
            self.photoOutput.capturePhoto(with: settings, delegate: delegate) //真正觸發拍照
        }
    }
    private func requestPermission() async -> Bool {
        //請求相機權限（async）
        switch AVCaptureDevice.authorizationStatus(for: .video) {  //讀取目前相機權限狀態
            case .authorized:
                //已授權
                return true
            case .notDetermined:
                //尚未詢問過
                return await AVCaptureDevice.requestAccess(for: .video)
                //跳出系統詢問視窗
            case .denied, .restricted:
                //被拒絕或受限制（家長控管等）
                return false
            @unknown default:
                //未來新增狀態
                return false
                //保守處理為不允許
        }
    }
    private func configureSession() {
        //配置相機 session（加入 input/output）
        if isConfigured { return }
        //已配置就不要重複做
        session.beginConfiguration()
        //開始批次配置（提高效率）
        session.sessionPreset = .photo
        
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front) else {
            //取得前鏡頭裝置
            session.commitConfiguration()
            //結束配置（避免 session 卡住）
            Task { @MainActor in self.overlayMessage = "找不到前鏡頭" }
            //顯示錯誤訊息
            return
            //停止配置流程
        }
        do {
            //建立 input 可能 throw
            let input = try AVCaptureDeviceInput(device: device)
            //用前鏡頭建立 input
            if session.canAddInput(input) { session.addInput(input) } //可加入就加入
            else {
                //不可加入 input
                session.commitConfiguration()
                //結束配置
                Task { @MainActor in self.overlayMessage = "無法加入相機輸入" }
                //顯示錯誤
                return
                //停止配置流程
            }
        } catch {
            //input 建立失敗
            session.commitConfiguration()
            //結束配置
            Task { @MainActor in self.overlayMessage = "相機輸入建立失敗" }
            //顯示錯誤
            return
        }
        if session.canAddOutput(photoOutput) {
            //檢查能否加入拍照輸出
            session.addOutput(photoOutput)
            //加入 photoOutput
        } else {
            //無法加入 output
            session.commitConfiguration()
            //結束配置
            Task { @MainActor in self.overlayMessage = "無法加入拍照輸出" }
            //顯示錯誤
            return
        }
        session.commitConfiguration()
        //提交配置（正式生效）
        isConfigured = true
        //標記為已配置
        Task { @MainActor in
            //回主執行緒更新 UI 狀態
            self.overlayMessage = nil
            //配置完成後隱藏遮罩
        }
    }
}
// MARK: - 拍照回呼
final class PhotoCaptureDelegate: NSObject, AVCapturePhotoCaptureDelegate { //AVCapturePhotoOutput 的代理
    private let onResult: (UIImage?) -> Void
    //回呼 closure（把 UIImage? 回傳出去）
    init(onResult: @escaping (UIImage?) -> Void) {
        //初始化時注入回呼
        self.onResult = onResult
        //保存回呼
    }
    func photoOutput(_ output: AVCapturePhotoOutput,
                     //拍照輸出回呼（系統呼叫）
                     didFinishProcessingPhoto photo: AVCapturePhoto,
                     //拍到的 photo 物件
                     error: Error?) {
        //可能的錯誤
        if error != nil {
            //若有錯誤
            Task { @MainActor in self.onResult(nil) }
            //回主執行緒回傳 nil
            return
        }
        guard let data = photo.fileDataRepresentation(),
              //把 photo 轉成 Data
              let image = UIImage(data: data) else {
            //把 Data 轉成 UIImage
            Task { @MainActor in self.onResult(nil) }
            //轉換失敗回傳 nil
            return
        }
        Task { @MainActor in
            //回到主執行緒（更新 SwiftUI 狀態較安全）
            self.onResult(image)
            //回傳成功的影像
        }
    }
}
// MARK: - 把 AVCaptureSession 接到 SwiftUI
struct CameraPreview: UIViewRepresentable {
    //把 UIView 放進 SwiftUI
    let session: AVCaptureSession
    //外部傳入的 session
    func makeUIView(context: Context) -> PreviewView {
        //建立 UIKit View（只呼叫一次）
        let v = PreviewView()
        //自訂 UIView,ayerClass 是 AVCaptureVideoPreviewLayer
        v.videoPreviewLayer.session = session
        //把 session 指給預覽 layer
        v.videoPreviewLayer.videoGravity = .resizeAspectFill
        //填滿畫面（裁切邊緣）
        v.updateOrientation()
        //設定直向與前鏡頭鏡像
        return v
        //回傳 UIKit View
    }
    func updateUIView(_ uiView: PreviewView, context: Context) {
        //SwiftUI 更新時呼叫（尺寸/狀態改變）
        uiView.videoPreviewLayer.session = session
        //確保 session 綁定正確
        uiView.updateOrientation()
        //確保方向/鏡像正確
    }
}
final class PreviewView: UIView {
    //自訂 UIView，承載 AVCaptureVideoPreviewLayer
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self } //定此 UIView 的 layer 就是預覽層
    var videoPreviewLayer: AVCaptureVideoPreviewLayer {             //方便取用強型別的預覽 layer
        layer as! AVCaptureVideoPreviewLayer
        //強制轉型（因為 layerClass 已指定）
    }
    override func layoutSubviews() {
        //UIView 佈局變化時呼叫（旋轉/尺寸變更）
        super.layoutSubviews()
        //先跑父類布局
        videoPreviewLayer.frame = bounds
        //讓預覽層永遠填滿此 view
        updateOrientation()
        //同步更新方向與鏡像
    }
    func updateOrientation() {
        //固定直向 + 前鏡頭鏡像
        guard let conn = videoPreviewLayer.connection else { return }
        //沒有連線就不處理
        if conn.isVideoOrientationSupported {
            //確認支援方向設定
            conn.videoOrientation = .portrait
            //固定 portrait
        }
        if conn.isVideoMirroringSupported {
            //確認支援鏡像
            conn.automaticallyAdjustsVideoMirroring = false
            //關閉系統自動調整
            conn.isVideoMirrored = true
            //開啟鏡像
        }
    }
}
// MARK: - SwiftUI Canvas Preview
//Xcode Canvas 預覽用（不影響真機）
#Preview {
    //Xcode 右側 Canvas 預覽入口
    ContentView()
    //預覽 ContentView
}
