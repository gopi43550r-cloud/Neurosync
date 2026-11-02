# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# Optional: bake the API base URL into the bundle. Leave unset for the default
# same-origin "/api" behaviour (frontend and API behind one reverse proxy).
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# --- serve stage ---
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# The nginx image renders *.template files from /etc/nginx/templates into
# /etc/nginx/conf.d/ at startup, substituting environment variables.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
