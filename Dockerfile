# 前端是純靜態站（沒有 build step，沒有 bundler），所以不需要多階段建置：
# 直接把檔案放進 nginx 就是完整的成品。
#
# ⚠️ 這行還沒釘 digest，後端的三個 Dockerfile 都有釘，這裡也應該要。
# 建立這個檔案時 Docker daemon 沒有執行，拿不到真實的 digest，而 digest 是不能
# 憑印象寫的——寫錯會讓 build 失敗，且錯誤訊息看起來像上游出問題。
#
# 補上的方式（Docker Desktop 起來之後）：
#   docker pull nginx:1.27-alpine
#   docker inspect --format='{{index .RepoDigests 0}}' nginx:1.27-alpine
# 把印出來的 nginx@sha256:... 貼成下面這行。
#
# 為什麼值得補：只寫 tag 的話，同一份 Dockerfile 今天與下個月會 build 出不同的
# 東西（上游 tag 會被覆寫）。釘住之後，升級就是一次看得見、進得了 review 的變更。
FROM nginx:1.27-alpine

# 預設站台設定會搶走 80 埠並蓋掉我們的 server 區塊，先移除。
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/decorate-me.conf

WORKDIR /usr/share/nginx/html

# 靜態資產：整包複製，由 .dockerignore 決定排除什麼。
#
# 後端的 Dockerfile 是逐項 COPY，這裡刻意不同。後端那樣做是因為它要從一個
# 混著訓練資料與模型權重的 repo 裡挑出少數幾支程式；前端整個目錄本來就是
# 要上線的東西，「挑著複製」反而會漏——第一版就漏了 pages/、recommendation/
# 與 favicon.svg，而靜態站漏檔不會 build 失敗，只會在點進某頁時 404。
#
# .dockerignore 與 firebase.json 的 hosting.ignore 對齊，所以映像內容
# 等於線上部署內容（唯一的差別是金鑰檔，見 .dockerignore 說明）。
COPY . .

# 容器內的本機設定。檔名必須是 config.local.js——index.html:170 寫死了這個名字，
# 而且只在 hostname 為 localhost/127.0.0.1 時才會注入它。
COPY config.docker.js ./config.local.js

# 上面的 COPY . . 會把建置用的檔案一起帶進網站根目錄。它們不含金鑰（金鑰檔在
# .dockerignore 裡擋掉了），但把 Dockerfile 與 nginx.conf 掛在公開網址上，
# 等於免費告訴別人這個站的內部結構，沒有理由這麼做。
#
# 這些檔案必須留在 build context 裡（COPY 得到它們），所以不能寫進 .dockerignore
# ——那樣 build 會直接失敗。刪除要在複製之後做。
RUN rm -f ./Dockerfile ./docker-compose.yml ./nginx.conf ./config.docker.js

# nginx 官方映像的 entrypoint 需要 root 來寫 /var/cache/nginx 與 pid 檔，
# worker process 本身已經降權到 nginx 使用者（見 /etc/nginx/nginx.conf 的 `user nginx;`），
# 所以對外服務的那顆 process 不是 root。
EXPOSE 8080

# nginx 映像預設的 CMD 就是前景執行，這裡明寫是為了讓意圖可讀。
CMD ["nginx", "-g", "daemon off;"]
