import { forgotPassword, confirmForgotPassword } from "./auth.js";
import { $, show, showMessage, handleSubmit, passwordsMatch } from "./ui.js";

let email = "";

handleSubmit($("#request-form"), async (data) => {
  email = data.get("email").trim();
  await forgotPassword(email);
  show("reset");
  showMessage("If that account exists, a reset code has been emailed.", "success");
});

handleSubmit($("#reset-form"), async (data) => {
  passwordsMatch(data);
  await confirmForgotPassword(email, data.get("code").trim(), data.get("password"));
  window.location.replace("login.html?reset=1");
});
