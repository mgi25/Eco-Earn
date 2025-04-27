// ========== Admin Graph Dashboard JS ==========

// Chart instances (to destroy when updating)
let usersChart, centersChart, itemsChart, transactionsChart;

// Load Admin Graph Data
async function loadAdminGraphData() {
  const fromDate = document.getElementById('from-date').value;
  const toDate = document.getElementById('to-date').value;

  try {
    const response = await fetch('/admin_graph/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_date: fromDate, to_date: toDate })
    });

    const data = await response.json();

    if (data.error) {
      alert(data.error);
      return;
    }

    // --- Users Growth Chart ---
    if (usersChart) usersChart.destroy();
    usersChart = new Chart(document.getElementById('usersGrowthChart'), {
      type: 'line',
      data: data.users_growth,
      options: {
        responsive: true,
        plugins: {
          title: { display: true, text: 'User Registrations Over Time' },
          tooltip: { mode: 'index', intersect: false },
          legend: { display: false }
        },
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: { y: { beginAtZero: true } }
      }
    });

    // --- Centers Growth Chart ---
    if (centersChart) centersChart.destroy();
    centersChart = new Chart(document.getElementById('centersGrowthChart'), {
      type: 'line',
      data: data.centers_growth,
      options: {
        responsive: true,
        plugins: {
          title: { display: true, text: 'Centers Registered Over Time' },
          tooltip: { mode: 'index', intersect: false },
          legend: { display: false }
        },
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: { y: { beginAtZero: true } }
      }
    });

    // --- Items Uploaded Chart ---
    if (itemsChart) itemsChart.destroy();
    itemsChart = new Chart(document.getElementById('itemsUploadedChart'), {
      type: 'bar',
      data: data.items_uploaded,
      options: {
        responsive: true,
        plugins: {
          title: { display: true, text: 'Items Uploaded Per Date' },
          legend: { display: false }
        },
        scales: { y: { beginAtZero: true } }
      }
    });

    // --- Transactions Split Chart ---
    if (transactionsChart) transactionsChart.destroy();
    transactionsChart = new Chart(document.getElementById('transactionsSplitChart'), {
      type: 'doughnut',
      data: data.transactions_split,
      options: {
        responsive: true,
        plugins: {
          title: { display: true, text: 'Reward Redeem vs Remaining' },
          legend: { position: 'bottom' }
        }
      }
    });

  } catch (error) {
    console.error('Failed to load admin graphs:', error);
    alert('Something went wrong loading admin graphs.');
  }
}

// Auto-fill default last 30 days on page load
function setDefaultAdminDates() {
  const today = new Date();
  const priorDate = new Date();
  priorDate.setDate(today.getDate() - 30);

  document.getElementById('to-date').value = today.toISOString().split('T')[0];
  document.getElementById('from-date').value = priorDate.toISOString().split('T')[0];
}

// ========== ON PAGE LOAD ==========
document.addEventListener('DOMContentLoaded', () => {
  setDefaultAdminDates();
  loadAdminGraphData();
});

// Attach Reload on Filter Button
document.getElementById('filter-btn').addEventListener('click', loadAdminGraphData);
