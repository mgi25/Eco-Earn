document.addEventListener("DOMContentLoaded", () => {
    const liveRadio = document.getElementById("live-location");
    const customRadio = document.getElementById("custom-location");
    const customFields = document.getElementById("custom-fields");
    const locationInput = document.getElementById("location");
  
    // Toggle fields
    liveRadio.addEventListener("change", () => {
      if (liveRadio.checked) {
        customFields.style.display = "none";
        navigator.geolocation.getCurrentPosition(
          (position) => {
            locationInput.value = `${position.coords.latitude},${position.coords.longitude}`;
          },
          () => {
            alert("Unable to fetch location. Please allow location access or use manual input.");
            customRadio.checked = true;
            customFields.style.display = "block";
          }
        );
      }
    });
  
    customRadio.addEventListener("change", () => {
      if (customRadio.checked) {
        customFields.style.display = "block";
        locationInput.value = "";
      }
    });
  });
  