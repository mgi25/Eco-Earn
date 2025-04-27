// ========== Dashboard JS Logic ==========

// Chart instances (to destroy before reloading)
let rewardsChart, itemsChart, materialsChart;

// Auto-fill default last 30 days on page load
function setDefaultDates() {
  const today = new Date();
  const priorDate = new Date();
  priorDate.setDate(today.getDate() - 30);

  document.getElementById('to-date').value = today.toISOString().split('T')[0];
  document.getElementById('from-date').value = priorDate.toISOString().split('T')[0];
}

// Load Dashboard Data from API
async function loadDashboardData() {
  const fromDate = document.getElementById('from-date').value;
  const toDate = document.getElementById('to-date').value;

  try {
    const response = await fetch('/user_dashboard/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_date: fromDate, to_date: toDate })
    });

    const data = await response.json();

    // Check if API error
    if (data.error) {
      alert(data.error);
      return;
    }

    // --- Draw Rewards Chart ---
    if (rewardsChart) rewardsChart.destroy();
    rewardsChart = new Chart(document.getElementById('rewardsChart'), {
      type: 'line',
      data: data.rewards,
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: 'Rewards Earned Over Time'
          },
          tooltip: {
            mode: 'index',
            intersect: false
          }
        },
        interaction: {
          mode: 'nearest',
          axis: 'x',
          intersect: false
        }
      }
    });

    // --- Draw Items Chart ---
    if (itemsChart) itemsChart.destroy();
    itemsChart = new Chart(document.getElementById('itemsChart'), {
      type: 'bar',
      data: data.items,
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: 'Items Recycled per Date'
          },
          legend: { display: false }
        }
      }
    });

    // --- Draw Materials Chart ---
    if (materialsChart) materialsChart.destroy();
    materialsChart = new Chart(document.getElementById('materialsChart'), {
      type: 'doughnut',
      data: data.materials,
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: 'Recycled Material Types'
          },
          legend: {
            position: 'bottom'
          }
        }
      }
    });

  } catch (error) {
    console.error('Error loading dashboard:', error);
    alert('Failed to load dashboard data.');
  }
}

// ========== ON PAGE LOAD ==========

// Set default dates + load graphs
document.addEventListener('DOMContentLoaded', () => {
  setDefaultDates();
  loadDashboardData();
});
