document.addEventListener("DOMContentLoaded", function () {
    // Filtering for recycling centers list (if present)
    const centerSearch = document.getElementById("centerSearch");
    if (centerSearch) {
      centerSearch.addEventListener("keyup", function () {
        const filter = centerSearch.value.toLowerCase();
        const centerItems = document.querySelectorAll(".center-item");
        centerItems.forEach(item => {
          const name = item.getAttribute("data-name").toLowerCase();
          const items = item.getAttribute("data-items").toLowerCase();
          if (name.includes(filter) || items.includes(filter)) {
            item.style.display = "";
          } else {
            item.style.display = "none";
          }
        });
      });
    }
    
    // "Show My Location & Sort" button handler for recycling centers page
    const getLocationBtn = document.getElementById("getLocationBtn");
    if (getLocationBtn) {
      getLocationBtn.addEventListener("click", function(){
        if (navigator.geolocation) {
          navigator.geolocation.getCurrentPosition(pos => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            window.location.href = "/recycling_centers?lat=" + lat + "&lon=" + lon;
          }, err => {
            alert("Could not get your location: " + err.message);
          });
        } else {
          alert("Geolocation not supported by this browser.");
        }
      });
    }
  });
  