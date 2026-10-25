idf_component_register(SRCS "main.c" INCLUDE_DIRS "." "../../private"
  REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_https_server esp_timer lwip
  EMBED_TXTFILES "../../private/servercert.pem" "../../private/prvtkey.pem")
