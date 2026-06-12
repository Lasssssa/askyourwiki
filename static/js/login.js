const form = document.getElementById("login-form");
const usernameEl = document.getElementById("login-username");
const passwordEl = document.getElementById("login-password");
const errorEl = document.getElementById("login-error");
const errorTextEl = document.getElementById("login-error-text");
const submitBtn = document.getElementById("login-submit");

function showError(message) {
  errorTextEl.textContent = message;
  errorEl.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorEl.hidden = true;
  submitBtn.disabled = true;

  try {
    const response = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: usernameEl.value,
        password: passwordEl.value,
      }),
    });

    if (response.ok) {
      window.location.href = "/";
      return;
    }

    const data = await response.json().catch(() => ({}));
    showError(data.error || "Sign in failed.");
  } catch (err) {
    showError(`Connection error: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
  }
});
