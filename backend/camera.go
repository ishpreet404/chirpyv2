package main

import (
	"net/http"
	"net/http/httputil"
	"net/url"
)

func cameraProxyHandler(targetURL string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		target, err := url.Parse(targetURL)
		if err != nil {
			http.Error(w, "invalid camera url", http.StatusInternalServerError)
			return
		}

		proxy := httputil.NewSingleHostReverseProxy(target)
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			http.Error(w, "camera unavailable", http.StatusBadGateway)
		}

		r.URL.Scheme = target.Scheme
		r.URL.Host = target.Host
		r.Host = target.Host
		r.URL.Path = target.Path

		proxy.ServeHTTP(w, r)
	}
}
