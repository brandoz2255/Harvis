# Use nginx:alpine as the base image
FROM nginx:alpine

# Change nginx to listen on 8089 instead of 80
RUN sed -i 's/listen       80;/listen       8089;/' /etc/nginx/conf.d/default.conf

# Copy the static files to the nginx html directory
COPY . /usr/share/nginx/html/

# Expose port 8089
EXPOSE 8089

# The default command will start nginx
CMD ["nginx", "-g", "daemon off;"] 