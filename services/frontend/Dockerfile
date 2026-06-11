# RAVEL frontend — multi-stage build (Adım 8k).
# Stage 1 (build): node 20 ile vite dist üret.
# Stage 2 (serve): nginx:alpine + nginx.conf + dist.

FROM node:20-alpine AS builder

WORKDIR /app

# Lock dosyamız yok (npm ci yerine npm install). Dependency listesi
# package.json'daki pinned semver'lere bağlı.
COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .
# Build sırasında VITE_* env'leri Vite tarafından gömülür; biz boş bırakıyoruz
# çünkü relative path + nginx upstream proxy yeterli.
RUN npm run build


FROM nginx:1.27-alpine AS runtime

# Default nginx.conf'u override
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx default CMD: nginx -g "daemon off;"
