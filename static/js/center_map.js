document.addEventListener("DOMContentLoaded", function () {
  // Get center data from hidden elements in the template
  const centerName = document.getElementById("centerName").textContent;
  const centerAddress = document.getElementById("centerAddress").textContent;
  const centerCoordinates = JSON.parse(document.getElementById("centerCoordinates").textContent); // [lon, lat]

  const centerData = {
    name: centerName,
    address: centerAddress,
    coordinates: centerCoordinates // [lon, lat]
  };

  // Initialize map centered on the center's location
  var map = L.map('map').setView([centerData.coordinates[1], centerData.coordinates[0]], 12);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  // Add a marker for the center location
  let centerMarker = L.marker([centerData.coordinates[1], centerData.coordinates[0]]).addTo(map);
  let popupText = "<strong>" + centerData.name + "</strong>";
  if (centerData.address) {
    popupText += "<br>" + centerData.address;
  }
  centerMarker.bindPopup(popupText).openPopup();

  // Try to retrieve and display the user's live location
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      function (position) {
        const userLat = position.coords.latitude;
        const userLon = position.coords.longitude;
        // Optionally, you might want to create a custom icon for the user's marker
        let userMarker = L.marker([userLat, userLon]).addTo(map);
        userMarker.bindPopup("<strong>Your Location</strong>").openPopup();
      },
      function (error) {
        console.log("Error retrieving live location:", error.message);
      }
    );
  } else {
    console.log("Geolocation is not supported by this browser.");
  }
});
