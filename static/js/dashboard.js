// ===============================
// Set Chart.js Defaults for Dark Mode
// ===============================
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

// ===============================
// Navigation between pages
// ===============================

const buttons = document.querySelectorAll(".nav-btn");
const pages = document.querySelectorAll(".page");

buttons.forEach((btn) => {
  btn.addEventListener("click", () => {
    buttons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    let page = btn.dataset.page;

    pages.forEach((p) => {
      p.classList.remove("active");

      if (p.id === page) {
        p.classList.add("active");
      }
    });
  });
});

// ===============================
// Invoice Processing Trends Chart
// ===============================

const trendChart = new Chart(document.getElementById("trendChart"), {
  type: "line",

  data: {
    labels: window.chartData ? window.chartData.trend_labels : ["Week 1", "Week 2", "Week 3", "Week 4"],

    datasets: [
      {
        label: "Processed",
        data: window.chartData ? window.chartData.trend_processed : [0,0,0,0],
        borderColor: "#22c55e",
        backgroundColor: "rgba(34,197,94,0.2)",
        fill: true,
        tension: 0.4,
      },

      {
        label: "Flagged",
        data: window.chartData ? window.chartData.trend_flagged : [0,0,0,0],
        borderColor: "#f59e0b",
        backgroundColor: "rgba(245,158,11,0.2)",
        fill: true,
        tension: 0.4,
      },

      {
        label: "Rejected",
        data: window.chartData ? window.chartData.trend_rejected : [0,0,0,0],
        borderColor: "#ef4444",
        backgroundColor: "rgba(239,68,68,0.2)",
        fill: true,
        tension: 0.4,
      },
    ],
  },

  options: {
    responsive: true,
    maintainAspectRatio: false,

    plugins: {
      legend: {
        display: false,
      },
    },
  },
});

// ===============================
// Risk Distribution Pie Chart
// ===============================

const riskChart = new Chart(document.getElementById("riskChart"), {
  type: "pie",

  data: {
    labels: window.chartData ? window.chartData.risk_labels : ["Low Risk", "Medium Risk", "High Risk", "Critical Risk"],

    datasets: [
      {
        data: window.chartData ? window.chartData.risk_data : [0, 0, 0, 0],

        backgroundColor: ["#10b981", "#f59e0b", "#fb923c", "#ef4444"],

        borderWidth: 2,
        borderColor: "#fff",
      },
    ],
  },

  options: {
    responsive: true,
    maintainAspectRatio: false,

    plugins: {
      legend: {
        position: "top",
      },
    },
  },
});

// ===============================
// Fraud Types Detected Chart
// ===============================

const fraudChart = new Chart(document.getElementById("fraudChart"), {
  type: "bar",

  data: {
    labels: window.chartData && window.chartData.fraud_labels.length > 0 ? window.chartData.fraud_labels : ["None"],

    datasets: [
      {
        label: "Fraud Cases",

        data: window.chartData && window.chartData.fraud_data.length > 0 ? window.chartData.fraud_data : [0],

        backgroundColor: "#ef4444",
        borderRadius: 6,
      },
    ],
  },

  options: {
    responsive: true,
    maintainAspectRatio: false,

    plugins: {
      legend: {
        display: false,
      },
    },

    scales: {
      y: {
        beginAtZero: true,
        ticks: {
          stepSize: 1,
        },
      },
    },
  },
});

const selectBtn = document.getElementById("selectBtn");
const fileInput = document.getElementById("fileInput");
const submitBtn = document.getElementById("submitBtn");

selectBtn.addEventListener("click", () => {
  fileInput.click();
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length > 0) {
    document.getElementById("fileName").textContent =
      "Selected file: " + fileInput.files[0].name;
    // Show the submit button so the user can process it
    submitBtn.style.display = "block";
  } else {
    submitBtn.style.display = "none";
  }
});

const uploadHeaderBtn = document.getElementById("uploadHeaderBtn");

uploadHeaderBtn.addEventListener("click", () => {
  // remove active class from nav buttons
  buttons.forEach((b) => b.classList.remove("active"));

  // hide all pages
  pages.forEach((p) => p.classList.remove("active"));

  // show upload page
  document.getElementById("upload").classList.add("active");
});

// Auto-switch to upload tab if activeTab is set (e.g., after form submission)
if (window.activeTab === "upload") {
  uploadHeaderBtn.click();
}