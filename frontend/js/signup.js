import { signUp, confirmSignUp, resendCode, currentUser } from "./auth.js";
import { $, show, showMessage, handleSubmit, passwordsMatch } from "./ui.js";

if (await currentUser()) window.location.replace("index.html");

let email = new URLSearchParams(window.location.search).get("verify");

function goToVerify(address) {
  email = address;
  $("#verify-email").textContent = address;
  show("verify");
}
if (email) goToVerify(email);

handleSubmit($("#signup-form"), async (data) => {
  passwordsMatch(data);
  const address = data.get("email").trim();
  await signUp(address, data.get("password"), data.get("firstName").trim(), data.get("lastName").trim());
  goToVerify(address);
  showMessage("Account created. Check your email for the verification code.", "success");
});

handleSubmit($("#verify-form"), async (data) => {
  await confirmSignUp(email, data.get("code").trim());
  window.location.replace("login.html?verified=1");
});

$("#resend").addEventListener("click", async () => {
  try {
    await resendCode(email);
    showMessage("A new code has been sent.", "success");
  } catch (err) {
    showMessage(err.message);
  }
});
