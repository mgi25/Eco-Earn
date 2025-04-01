// static/js/recycling_centers.js

document.addEventListener("DOMContentLoaded", function () {
    var userLatInput = document.getElementById("userLat");
    var userLonInput = document.getElementById("userLon");
  
    // If we didn't get userLat/userLon from Flask, try geolocation in the browser
    if (!userLatInput || !userLonInput) {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(function(pos) {
          var lat = pos.coords.latitude;
          var lon = pos.coords.longitude;
          // Reload page with lat/lon so Flask can do a $near query
          window.location.href = "/recycling_centers?lat=" + lat + "&lon=" + lon;
        }, function(err) {
          console.log("Geolocation error:", err);
          // If geolocation fails or user denies, just init the map with defaults
          initMap(null, null);
        });
      } else {
        // Geolocation not supported
        initMap(null, null);
      }
    } else {
      // We have user location from Flask
      var latVal = parseFloat(userLatInput.value);
      var lonVal = parseFloat(userLonInput.value);
      initMap(latVal, lonVal);
    }
  
    /**
     * Initializes the Leaflet map. If lat/lon are valid numbers, use them.
     * Otherwise, default to a fallback location (e.g., center of India).
     */
    function initMap(lat, lon) {
      var map = L.map("map");
  
      // Default fallback location
      var defaultLat = 20.5937;  // India
      var defaultLon = 78.9629;  // India
      var defaultZoom = 5;
  
      // If lat/lon is valid, center on user location
      if (lat !== null && lon !== null && !isNaN(lat) && !isNaN(lon)) {
        defaultLat = lat;
        defaultLon = lon;
        defaultZoom = 13;
      }
  
      // Set the view
      map.setView([defaultLat, defaultLon], defaultZoom);
  
      // Add OSM tile layer
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(map);
  
      // If we have a valid user location, add a "You are here" marker
      if (lat !== null && lon !== null && !isNaN(lat) && !isNaN(lon)) {
        var userMarker = L.marker([lat, lon]).addTo(map);
        userMarker.bindPopup("<strong>Your Location</strong>").openPopup();
      }
  
      // Add markers for each recycling center
      var centerItems = document.querySelectorAll(".center-card.center-item");
      centerItems.forEach(function(item) {
        var latStr = item.getAttribute("data-lat");
        var lonStr = item.getAttribute("data-lon");
        var name = item.getAttribute("data-name");
  
        if (latStr && lonStr) {
          var cLat = parseFloat(latStr);
          var cLon = parseFloat(lonStr);
          if (!isNaN(cLat) && !isNaN(cLon)) {
            var marker = L.marker([cLat, cLon]).addTo(map);
            marker.bindPopup("<strong>" + name + "</strong>");
          }
        }
      });
    }
  });
  