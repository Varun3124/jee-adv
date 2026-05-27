const form = document.querySelector("#submit-form");
if (form) {
  form.addEventListener("submit", () => {
    const loading = document.querySelector("#loading");
    if (loading) loading.hidden = false;
  });
}

const sectionCanvas = document.querySelector("#sectionChart");
if (sectionCanvas) {
  fetch(`/api/analysis/${sectionCanvas.dataset.session}/section-breakdown`)
    .then((response) => response.json())
    .then((data) => {
      const labels = data.sections.map((item) => `P${item.paper} ${item.subject} ${item.section}`);
      new Chart(sectionCanvas, {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "Marks", data: data.sections.map((item) => item.score), backgroundColor: "#0f766e" },
            { label: "Max", data: data.sections.map((item) => item.max_score), backgroundColor: "#94a3b8" },
          ],
        },
        options: { responsive: true, scales: { y: { beginAtZero: true } } },
      });
    });
}

const distributionCanvas = document.querySelector("#distributionChart");
if (distributionCanvas) {
  fetch(`/api/analysis/${distributionCanvas.dataset.session}/score-distribution`)
    .then((response) => response.json())
    .then((data) => {
      new Chart(distributionCanvas, {
        type: "bar",
        data: {
          labels: data.buckets.map((item) => item.label),
          datasets: [{ label: "Submissions", data: data.buckets.map((item) => item.count), backgroundColor: "#0f766e" }],
        },
        options: { responsive: true, plugins: { annotation: false }, scales: { y: { beginAtZero: true } } },
      });
    });
}

const state = { paper: "1", subject: "Physics" };
document.querySelectorAll(".tabs .tab").forEach((button) => {
  button.addEventListener("click", () => {
    const group = button.closest(".tabs").dataset.filterGroup;
    button.closest(".tabs").querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    button.classList.add("active");
    state[group] = button.dataset[group];
    refreshQuestions();
  });
});

function refreshQuestions() {
  const chips = Array.from(document.querySelectorAll(".qchip"));
  const details = Array.from(document.querySelectorAll(".qdetail"));
  let firstVisible = null;
  chips.forEach((chip) => {
    const visible = chip.dataset.paper === state.paper && chip.dataset.subject === state.subject;
    chip.hidden = !visible;
    if (visible && !firstVisible) firstVisible = chip;
  });
  details.forEach((detail) => {
    detail.classList.remove("active");
    detail.hidden = !(detail.dataset.paper === state.paper && detail.dataset.subject === state.subject);
  });
  if (firstVisible) showQuestion(firstVisible.dataset.target);
}

document.querySelectorAll(".qchip").forEach((chip) => chip.addEventListener("click", () => showQuestion(chip.dataset.target)));

function showQuestion(id) {
  document.querySelectorAll(".qdetail").forEach((detail) => detail.classList.remove("active"));
  const detail = document.getElementById(id);
  if (detail) detail.classList.add("active");
}
if (document.querySelector("#questionGrid")) refreshQuestions();

const josaaForm = document.querySelector("#josaaForm");
if (josaaForm) {
  josaaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadJosaa();
  });
  loadJosaa();
}

function loadJosaa() {
  const params = new URLSearchParams(new FormData(josaaForm));
  fetch(`/api/josaa-predict/${josaaForm.dataset.session}?${params.toString()}`)
    .then((response) => response.json())
    .then((data) => {
      const tbody = document.querySelector("#josaaTable tbody");
      tbody.innerHTML = "";
      if (!data.results.length) {
        tbody.innerHTML = "<tr><td colspan='4'>No matching rows found.</td></tr>";
        return;
      }
      data.results.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${escapeHtml(row.institute)}</td><td>${escapeHtml(row.program)}</td><td>${escapeHtml(row.round)}</td><td>${row.closing_rank}</td>`;
        tbody.appendChild(tr);
      });
    });
}

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value ?? "";
  return span.innerHTML;
}

// Admin student management helpers
const selectAllCheckbox = document.querySelector('#selectAll');
if (selectAllCheckbox) {
  selectAllCheckbox.addEventListener('change', () => {
    document.querySelectorAll('input[name="ids"]').forEach((cb) => {
      cb.checked = selectAllCheckbox.checked;
    });
  });
}

const bulkDeleteBtn = document.querySelector('#bulkDeleteBtn');
if (bulkDeleteBtn) {
  bulkDeleteBtn.addEventListener('click', (e) => {
    const checked = document.querySelectorAll('input[name="ids"]:checked');
    if (checked.length === 0) {
      e.preventDefault();
      alert('No entries selected.');
      return;
    }
    if (!confirm(`Delete ${checked.length} selected entry/entries?`)) {
      e.preventDefault();
    }
  });
}
