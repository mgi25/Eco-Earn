let videoStream = null;
let capturedPhotos = [];

function startCamera() {
  const video = document.getElementById('cameraPreview');
  if (!navigator.mediaDevices?.getUserMedia) {
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

async function takePicture() {
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

  const originalDataURL = canvas.toDataURL('image/jpeg');
  const resized = await resizeImage(originalDataURL);
  capturedPhotos.push(resized);
  renderThumbnails();
}

function handleFileSelect(event) {
  const files = event.target.files;
  if (!files.length) return;

  Array.from(files).forEach(file => {
    const reader = new FileReader();
    reader.onload = async e => {
      const resized = await resizeImage(e.target.result);
      capturedPhotos.push(resized);
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
  container.innerHTML = '';

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

function resizeImage(base64Str, maxWidth = 800, maxHeight = 800) {
  return new Promise((resolve) => {
    const img = new Image();
    img.src = base64Str;
    img.onload = () => {
      let canvas = document.createElement("canvas");
      let width = img.width;
      let height = img.height;

      if (width > maxWidth) {
        height = (maxWidth / width) * height;
        width = maxWidth;
      }
      if (height > maxHeight) {
        width = (maxHeight / height) * width;
        height = maxHeight;
      }

      canvas.width = width;
      canvas.height = height;

      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, width, height);

      resolve(canvas.toDataURL("image/jpeg", 0.8));
    };
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
    uploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();

      const files = fileInput.files;
      const overlay = document.getElementById('loadingOverlay');
      overlay.style.display = 'flex';

      // If file was chosen
      if (files.length > 0) {
        uploadForm.submit();
        return;
      }

      // If captured image available
      if (capturedPhotos.length === 0) {
        alert("Please capture or select an image first.");
        overlay.style.display = 'none';
        return;
      }

      const base64 = capturedPhotos[0];
      const blob = await fetch(base64).then(res => res.blob());
      const formData = new FormData();
      formData.append('captured_image', blob, 'captured.jpg');

      fetch('/scan_item', {
        method: 'POST',
        body: formData
      })
      .then(res => {
        if (res.redirected) {
          window.location.href = res.url;
        } else {
          alert("Upload failed.");
          overlay.style.display = 'none';
        }
      })
      .catch(err => {
        console.error(err);
        alert("Upload error: " + err.message);
        overlay.style.display = 'none';
      });
    });
  }
});
