// static/js/camera.js

let videoStream = null;
let capturedPhotos = []; // array of base64 strings from camera & files

function startCamera() {
  const video = document.getElementById('cameraPreview');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert("Camera not supported by this browser/device.");
    return;
  }

  navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
    .then(stream => {
      videoStream = stream;
      video.srcObject = stream;
      video.play();
    })
    .catch(err => {
      console.error("Camera error:", err);
      alert("Error accessing camera: " + err.message);
    });
}

function takePicture() {
  const video = document.getElementById('cameraPreview');
  if (!videoStream) {
    alert("Camera is not running. Please open camera first!");
    return;
  }

  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  const dataURL = canvas.toDataURL('image/png');
  capturedPhotos.push(dataURL);
  renderThumbnails();
}

function handleFileSelect(event) {
  const files = event.target.files; // a FileList of all selected files
  if (!files.length) return;

  // read each file as base64
  Array.from(files).forEach(file => {
    const reader = new FileReader();
    reader.onload = e => {
      const dataURL = e.target.result; // base64 string
      capturedPhotos.push(dataURL);
      renderThumbnails();
    };
    reader.readAsDataURL(file);
  });
}

function removePhoto(index) {
  capturedPhotos.splice(index, 1);
  renderThumbnails();
}

function renderThumbnails() {
  const container = document.getElementById('thumbnailsContainer');
  container.innerHTML = ''; // clear old content

  capturedPhotos.forEach((photo, index) => {
    const thumbDiv = document.createElement('div');
    thumbDiv.classList.add('thumbnail');

    const img = document.createElement('img');
    img.src = photo;
    img.alt = `Image ${index + 1}`;

    const removeBtn = document.createElement('span');
    removeBtn.classList.add('remove-btn');
    removeBtn.innerText = 'X';
    removeBtn.onclick = () => removePhoto(index);

    thumbDiv.appendChild(img);
    thumbDiv.appendChild(removeBtn);
    container.appendChild(thumbDiv);
  });
}

window.addEventListener('DOMContentLoaded', () => {
  const selectBtn = document.getElementById('selectCameraBtn');
  const takeBtn = document.getElementById('takePictureBtn');
  const fileInput = document.getElementById('fileInput');
  const uploadForm = document.getElementById('uploadForm');

  if (selectBtn) selectBtn.addEventListener('click', startCamera);
  if (takeBtn) takeBtn.addEventListener('click', takePicture);
  if (fileInput) fileInput.addEventListener('change', handleFileSelect);

  if (uploadForm) {
    uploadForm.addEventListener('submit', () => {
      const hiddenInput = document.getElementById('photosBase64');
      hiddenInput.value = JSON.stringify(capturedPhotos);
    });
  }
});
