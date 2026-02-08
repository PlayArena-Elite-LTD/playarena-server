document.addEventListener("DOMContentLoaded", () => {
  const navMenu = document.getElementById("nav-menu"),
    navToggle = document.getElementById("nav-toggle"),
    navClose = document.getElementById("nav-close"),
    overlay = document.getElementById("overlay");

  /*===== MENU SHOW =====*/
  /* Validate if constant exists */
  if (navToggle) {
    navToggle.addEventListener("click", () => {
      navMenu.classList.add("show-menu");
      overlay.classList.add("active"); // Show overlay when menu opens
    });
  }

  /*===== MENU HIDDEN =====*/
  /* Validate if constant exists */
  if (navClose) {
    navClose.addEventListener("click", () => {
      // First remove the show-menu class to start the closing animation
      navMenu.classList.remove("show-menu");
      overlay.classList.remove("active"); // Hide overlay when menu closes
    });
  }

  /*=============== OVERLAY CLICK CLOSES MENU ===============*/
  overlay.addEventListener("click", () => {
    navMenu.classList.remove("show-menu");
    overlay.classList.remove("active");
  });

  /*=============== REMOVE MENU MOBILE WHEN NAV LINK CLICKED ===============*/
  const navLinks = document.querySelectorAll(".nav-link");

  const linkAction = () => {
    const navMenu = document.getElementById("nav-menu");
    // When we click on each nav__link, we remove the show-menu class
    navMenu.classList.remove("show-menu");
    overlay.classList.remove("active"); // Also hide overlay
  };
  navLinks.forEach(n => n.addEventListener("click", linkAction));

  /*=============== DARK LIGHT THEME ===============*/
  const themeToggle = document.getElementById("theme-toggle");
  const body = document.body;

  // Check if user previously selected dark theme
  const selectedTheme = localStorage.getItem("selected-theme");

  // Apply saved theme if it exists
  if (selectedTheme === "dark") {
    body.classList.add("dark-theme");
    // Change moon icon to sun icon
    themeToggle.classList.remove("fa-moon");
    themeToggle.classList.add("fa-sun");
  }

  // Toggle theme on click
  themeToggle.addEventListener("click", () => {
    // Add animation class
    themeToggle.classList.add("animate");

    // Toggle dark-theme class on body
    body.classList.toggle("dark-theme");

    // Update icon (moon to sun or sun to moon)
    if (body.classList.contains("dark-theme")) {
      themeToggle.classList.remove("fa-moon");
      themeToggle.classList.add("fa-sun");
      localStorage.setItem("selected-theme", "dark");
    } else {
      themeToggle.classList.remove("fa-sun");
      themeToggle.classList.add("fa-moon");
      localStorage.setItem("selected-theme", "light");
    }

    // Remove animation class after animation completes
    setTimeout(() => {
      themeToggle.classList.remove("animate");
    }, 500);
  });

  /*=============== SCROLL HEADER SHADOW ===============*/
  function scrollHeader() {
    const header = document.querySelector(".header");
    // When the scroll is greater than 50 viewport height, add the scroll-header class
    if (this.scrollY >= 50) header.classList.add("scroll-header");
    else header.classList.remove("scroll-header");
  }
  window.addEventListener("scroll", scrollHeader);

  /*=============== ADJUST SLIDER SPEED BASED ON SCREEN WIDTH ===============*/
  function adjustSliderSpeed() {
    const slider = document.querySelector(".games-slider");
    if (slider) {
      // Adjust animation duration based on screen width
      const duration = window.innerWidth < 768 ? "20s" : "30s";
      slider.style.animationDuration = duration;
    }
  }

  // Run on page load and window resize
  window.addEventListener("load", adjustSliderSpeed);
  window.addEventListener("resize", adjustSliderSpeed);

  /*=============== FAQ ACCORDION ===============*/
  const faqItems = document.querySelectorAll(".faq-item");

  faqItems.forEach(item => {
    const header = item.querySelector(".faq-header");
    const content = item.querySelector(".faq-content");
    const answer = item.querySelector(".faq-answer");

    header.addEventListener("click", () => {
      // Close all other open FAQ items
      faqItems.forEach(otherItem => {
        if (otherItem !== item && otherItem.classList.contains("active")) {
          otherItem.classList.remove("active");
          otherItem.querySelector(".faq-content").style.height = "0px";
        }
      });

      // Toggle current item
      const isItemActive = item.classList.contains("active");

      if (isItemActive) {
        // Close the item
        item.classList.remove("active");
        content.style.height = "0px";
      } else {
        // Open the item
        item.classList.add("active");
        content.style.height = answer.offsetHeight + "px";
      }
    });

    // Initialize heights to 0
    content.style.height = "0px";
  });

  // Open the first FAQ item by default (optional)
  if (faqItems.length > 0) {
    const firstItem = faqItems[0];
    const firstContent = firstItem.querySelector(".faq-content");
    const firstAnswer = firstItem.querySelector(".faq-answer");

    firstItem.classList.add("active");
    firstContent.style.height = firstAnswer.offsetHeight + "px";
  }

  // Update FAQ heights on window resize
  window.addEventListener("resize", () => {
    const activeItems = document.querySelectorAll(".faq-item.active");

    activeItems.forEach(item => {
      const content = item.querySelector(".faq-content");
      const answer = item.querySelector(".faq-answer");

      content.style.height = answer.offsetHeight + "px";
    });
  });

  // Footer date
  document.getElementById("current-year").textContent = new Date().getFullYear();

  /*=============== FADE-IN ON SCROLL ===============*/
  // Professional fade-in animation for sections and cards
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };

  const fadeInObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        // Stop observing once animated
        fadeInObserver.unobserve(entry.target);
      }
    });
  }, observerOptions);

  // Observe all sections for fade-in
  const sections = document.querySelectorAll('.section');
  sections.forEach(section => {
    section.classList.add('section-fade-in');
    fadeInObserver.observe(section);
  });

  // Observe cards for staggered fade-in
  const cards = document.querySelectorAll('.about-card, .trust-badge, .trust-indicator, .pricing-benefit, .games-category');
  cards.forEach((card, index) => {
    card.classList.add('card-fade-in');
    // Add slight delay for staggered effect
    card.style.transitionDelay = `${index * 0.1}s`;
    fadeInObserver.observe(card);
  });
});