const form = document.getElementById("login-form");
const usernameEl = document.getElementById("login-username");
const passwordEl = document.getElementById("login-password");
const errorEl = document.getElementById("login-error");
const submitBtn = document.getElementById("login-submit");

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
    errorEl.textContent = data.error || "Sign in failed.";
    errorEl.hidden = false;
  } catch (err) {
    errorEl.textContent = `Connection error: ${err.message}`;
    errorEl.hidden = false;
  } finally {
    submitBtn.disabled = false;
  }
});
