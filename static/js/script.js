'use strict';

/**
 * add event on element
 */

const addEventOnElem = function (elem, type, callback) {
  if (elem.length > 1) {
    for (let i = 0; i < elem.length; i++) {
      elem[i].addEventListener(type, callback);
    }
  } else {
    elem.addEventListener(type, callback);
  }
}

/**
 * navbar toggle
 */

const navbar = document.querySelector("[data-navbar]");
const navbarLinks = document.querySelectorAll("[data-nav-link]");
const navToggler = document.querySelector("[data-nav-toggler]");

const toggleNavbar = function () {
  navbar.classList.toggle("active");
  this.classList.toggle("active");
}

addEventOnElem(navToggler, "click", toggleNavbar);

const closeNavbar = function () {
  navbar.classList.remove("active");
  navToggler.classList.remove("active");
}

addEventOnElem(navbarLinks, "click", closeNavbar);

function openModal(modalId) {
  document.getElementById(modalId).style.display = "flex";
}

function closeModal(modalId) {
  document.getElementById(modalId).style.display = "none";
}

// login/Sign up functionality
let signup = document.querySelector(".login-signup");
let login = document.querySelector(".login-login");
let slider = document.querySelector(".login-slider");
let formSection = document.querySelector(".login-form-section");

signup.addEventListener("click", () => {
    slider.classList.add("login-moveslider");
    formSection.classList.add("login-form-section-move");
});

login.addEventListener("click", () => {
    slider.classList.remove("login-moveslider");
    formSection.classList.remove("login-form-section-move");
});

// Username validation
document.getElementById('username').addEventListener('input', function() {
    var usernameInput = document.getElementById('username');
    var errorMessage = document.getElementById('username-error');
    var existingUsernames = fetch('check_user/<username>/'); // Static list for demonstration

    if (existingUsernames.success === false) {
        errorMessage.textContent = 'Username already taken';
        errorMessage.classList.add('active');
    } else {
        errorMessage.textContent = ' ';
        errorMessage.classList.remove('active');
    }
});

// Password matching validation
document.getElementById('ConfirmPassword').addEventListener('input', function() {
    var passwordInput = document.getElementById('password');
    var confirmPasswordInput = document.getElementById('ConfirmPassword');
    var errorMessage = document.getElementById('password-match-error');

    if (passwordInput.value === confirmPasswordInput.value) {
        errorMessage.textContent = 'Passwords match';
        errorMessage.classList.remove('no-match');
        errorMessage.classList.add('match');
    } else {
        errorMessage.textContent = 'Passwords do not match';
        errorMessage.classList.remove('match');
        errorMessage.classList.add('no-match');
    }
});

// Toggle password visibility
function togglePassword(fieldId, icon) {
    var passwordField = document.getElementById(fieldId);
    var passwordFieldType = passwordField.getAttribute('type');

    if (passwordFieldType === 'password') {
        passwordField.setAttribute('type', 'text');
        icon.classList.remove('bx-hide');
        icon.classList.add('bx-show');
    } else {
        passwordField.setAttribute('type', 'password');
        icon.classList.remove('bx-show');
        icon.classList.add('bx-hide');
    }
}

//Toast
let toastBox = document.getElementById('toastBox');
let loginmsg = '<i class="fa-solid fa-square-check"></i>Welcome Back User!. Learn Well';
let signupmsg = '<i class="fa-solid fa-thumbs-up"></i>Welcome User. Click next to fill out details ';

function showToast(msg) {
    let toast = document.createElement('div');
    toast.classList.add('toast');
    toast.innerHTML = msg;
    toastBox.appendChild(toast);

    if(msg.includes('successfully')){
        toast.classList.add('error');
    }

    setTimeout(()=>{
        toast.remove();
    },5000);
}

// channels
function openModal(modalId) {
    document.getElementById(modalId).style.display = "flex";
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = "none";
}

//faqs
function toggleFaq(element) {
    const faq = element.parentElement;
    faq.classList.toggle("open");
}

//ChatBot

function toggleChatbot() {
    const chatbotContainer = document.getElementById('chatbotContainer');
    chatbotContainer.style.display = chatbotContainer.style.display === 'none' ? 'block' : 'none';
}

async function sendMessage() {
    const input = document.getElementById('chatbotInput');
    const message = input.value;
    if (message.trim() === '') return;

    displayMessage('You', message);
    input.value = '';

    try {
        const response = await getChatbotResponse(message);
        displayMessage('Bot', response.answer); // Assuming response is structured as {'answer': ...}
    } catch (error) {
        console.error('Error:', error);
        // Handle error display or logging as needed
    }
}

function displayMessage(sender, message) {
    const messagesContainer = document.getElementById('chatbotMessages');
    const messageElement = document.createElement('div');
    messageElement.textContent = `${sender}: ${message}`;
    messagesContainer.appendChild(messageElement);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function getChatbotResponse(message) {
    const response = await fetch('http://127.0.0.1:8000/api/chatbot/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ question: message })
    });     
    console.log(response);
    if (!response.ok) {
        throw new Error('Network response was not ok');
    }
    return await response.json();

}