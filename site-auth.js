// ============================================================
// site-auth.js — Jackson Habimana Chemistry Portal
// Site-wide login gate. Include with:
// <script src="site-auth.js" defer></script>
// in every page's <head> that should require login.
// ============================================================

(function(){
  const LOGIN_URL = 'https://chem-payment.hajackson2020.workers.dev/teachers/login';
  const REGISTER_URL = 'https://chem-payment.hajackson2020.workers.dev/teachers/self-register';

  // If already logged in, do nothing
  if (localStorage.getItem('teacher_token')) return;

  document.addEventListener('DOMContentLoaded', injectGate);
  if (document.readyState === 'complete' || document.readyState === 'interactive') injectGate();

  function injectGate(){
    if (document.getElementById('site-auth-gate')) return;

    const gate = document.createElement('div');
    gate.id = 'site-auth-gate';
    gate.style.cssText = 'position:fixed;inset:0;background:#f3f4f6;z-index:99999;display:flex;align-items:center;justify-content:center;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:20px;';

    gate.innerHTML = `
      <div style="background:#fff;border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,.12);padding:36px 32px;max-width:400px;width:100%;">

        <div id="sa-login-box">
          <h1 style="font-size:1.4rem;font-weight:800;color:#111827;margin-bottom:6px;">WELCOME TO JACKSON HABIMANA CHEMISTRY PORTAL</h1>
          <p style="color:#6b7280;font-size:.9rem;margin-bottom:22px;">Sign in to your account to continue</p>

          <label style="display:block;font-size:.72rem;font-weight:700;color:#374151;letter-spacing:.5px;margin-bottom:6px;">EMAIL ADDRESS</label>
          <input type="text" id="sa-username" placeholder="you@example.com" style="width:100%;border:1px solid #d1d5db;border-radius:10px;padding:12px 14px;font-size:.92rem;margin-bottom:16px;outline:none;"/>

          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <label style="font-size:.72rem;font-weight:700;color:#374151;letter-spacing:.5px;">PASSWORD</label>
          </div>
          <input type="password" id="sa-password" placeholder="Enter your password" onkeydown="if(event.key==='Enter')window.__saLogin()" style="width:100%;border:1px solid #d1d5db;border-radius:10px;padding:12px 14px;font-size:.92rem;margin-bottom:18px;outline:none;"/>

          <button onclick="window.__saLogin()" style="width:100%;background:linear-gradient(135deg,#374151,#1f2937);color:#fff;border:none;border-radius:10px;padding:13px;font-weight:700;font-size:.93rem;cursor:pointer;">Sign in</button>

          <p id="sa-login-error" style="color:#dc2626;font-size:.83rem;margin-top:12px;display:none;"></p>

          <p style="text-align:center;margin-top:18px;font-size:.85rem;color:#6b7280;">New here? <a href="#" onclick="window.__saShowRegister();return false;" style="color:#374151;font-weight:700;text-decoration:none;">Create an account</a></p>
        </div>

        <div id="sa-register-box" style="display:none;">
          <h1 style="font-size:1.4rem;font-weight:800;color:#111827;margin-bottom:6px;">CREATE YOUR ACCOUNT</h1>
          <p style="color:#6b7280;font-size:.9rem;margin-bottom:22px;">Join Jackson Habimana Chemistry Portal</p>

          <label style="display:block;font-size:.72rem;font-weight:700;color:#374151;letter-spacing:.5px;margin-bottom:6px;">FULL NAME</label>
          <input type="text" id="sa-reg-name" placeholder="Your full name" style="width:100%;border:1px solid #d1d5db;border-radius:10px;padding:12px 14px;font-size:.92rem;margin-bottom:16px;outline:none;"/>

          <label style="display:block;font-size:.72rem;font-weight:700;color:#374151;letter-spacing:.5px;margin-bottom:6px;">EMAIL ADDRESS</label>
          <input type="text" id="sa-reg-username" placeholder="you@example.com" style="width:100%;border:1px solid #d1d5db;border-radius:10px;padding:12px 14px;font-size:.92rem;margin-bottom:16px;outline:none;"/>

          <label style="display:block;font-size:.72rem;font-weight:700;color:#374151;letter-spacing:.5px;margin-bottom:6px;">PASSWORD</label>
          <input type="password" id="sa-reg-password" placeholder="Choose a password (min 4 chars)" onkeydown="if(event.key==='Enter')window.__saRegister()" style="width:100%;border:1px solid #d1d5db;border-radius:10px;padding:12px 14px;font-size:.92rem;margin-bottom:18px;outline:none;"/>

          <button onclick="window.__saRegister()" style="width:100%;background:linear-gradient(135deg,#374151,#1f2937);color:#fff;border:none;border-radius:10px;padding:13px;font-weight:700;font-size:.93rem;cursor:pointer;">Create account</button>

          <p id="sa-register-error" style="color:#dc2626;font-size:.83rem;margin-top:12px;display:none;"></p>

          <p style="text-align:center;margin-top:18px;font-size:.85rem;color:#6b7280;">Already have an account? <a href="#" onclick="window.__saShowLogin();return false;" style="color:#374151;font-weight:700;text-decoration:none;">Sign in</a></p>
        </div>

      </div>`;

    document.body.appendChild(gate);
    document.body.style.overflow = 'hidden';

    window.__saShowRegister = function(){
      document.getElementById('sa-login-box').style.display = 'none';
      document.getElementById('sa-register-box').style.display = 'block';
    };
    window.__saShowLogin = function(){
      document.getElementById('sa-register-box').style.display = 'none';
      document.getElementById('sa-login-box').style.display = 'block';
    };

    window.__saLogin = async function(){
      const username = document.getElementById('sa-username').value.trim().toLowerCase();
      const password = document.getElementById('sa-password').value;
      const err = document.getElementById('sa-login-error');
      err.style.display = 'none';
      if (!username || !password) return;
      try {
        const r = await fetch(LOGIN_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        const d = await r.json();
        if (r.ok && d.token) {
          saSuccess(d.token, d.name, username);
        } else {
          err.textContent = d.error || 'Invalid email or password.';
          err.style.display = 'block';
        }
      } catch(e) {
        err.textContent = 'Network error. Please try again.';
        err.style.display = 'block';
      }
    };

    window.__saRegister = async function(){
      const name = document.getElementById('sa-reg-name').value.trim();
      const username = document.getElementById('sa-reg-username').value.trim().toLowerCase();
      const password = document.getElementById('sa-reg-password').value;
      const err = document.getElementById('sa-register-error');
      err.style.display = 'none';
      if (!name || !username || !password) {
        err.textContent = 'Please fill in all fields.';
        err.style.display = 'block';
        return;
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(username)) {
        err.textContent = 'Please enter a valid email address (for example name@gmail.com).';
        err.style.display = 'block';
        return;
      }
      try {
        const r = await fetch(REGISTER_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password, name })
        });
        const d = await r.json();
        if (r.ok && d.token) {
          saSuccess(d.token, d.name, d.username);
        } else {
          err.textContent = d.error || 'Registration failed. Please try again.';
          err.style.display = 'block';
        }
      } catch(e) {
        err.textContent = 'Network error. Please try again.';
        err.style.display = 'block';
      }
    };

    function saSuccess(token, name, username){
      localStorage.setItem('teacher_token', token);
      localStorage.setItem('teacher_name', name || username);
      // The email is the account identity: pages use it to keep each account's data separate.
      localStorage.setItem('teacher_email', String(username || '').trim().toLowerCase());
      document.body.style.overflow = '';
      gate.remove();
      window.dispatchEvent(new Event('site-auth-login'));
    }
  }
})();

// Global logout helper, usable from any page: window.siteLogout()
window.siteLogout = function(){
  localStorage.removeItem('teacher_token');
  localStorage.removeItem('teacher_name');
  localStorage.removeItem('teacher_email');
  location.reload();
};
