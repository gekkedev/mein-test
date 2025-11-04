const STORAGE_KEY = "mein-test-known-v1";
const SPLASH_MIN_DURATION_MS = 2000;

const elements = {
  filterMode: document.querySelector("#filter-mode"),
  progressCount: document.querySelector("#progress-count"),
  unknownCount: document.querySelector("#unknown-count"),
  solutionCount: document.querySelector("#solution-count"),
  markKnown: document.querySelector("#mark-known"),
  markUnknown: document.querySelector("#mark-unknown"),
  nextQuestion: document.querySelector("#next-question"),
  resetProgress: document.querySelector("#reset-progress"),
  questionNumberInput: document.querySelector("#question-number-input"),
  jumpToQuestion: document.querySelector("#jump-to-question"),
  status: document.querySelector("#status"),
  card: document.querySelector("#question-card"),
  sectionInfo: document.querySelector("#section-info"),
  questionNumber: document.querySelector("#question-number"),
  questionPages: document.querySelector("#question-pages"),
  questionText: document.querySelector("#question-text"),
  answers: document.querySelector("#answers"),
  imageWrapper: document.querySelector("#image-wrapper"),
  splashScreen: document.querySelector("#splash-screen"),
  imageLightbox: document.querySelector("#image-lightbox"),
  lightboxImage: document.querySelector("#lightbox-image"),
  closeLightbox: document.querySelector("#close-lightbox"),
};

const state = {
  questions: [],
  knownIds: new Set(),
  mode: "unknown",
  currentQuestion: null,
  selectedAnswerIndex: null,
  attemptedAnswers: new Set(),
  isQuestionSolved: false,
  lastFocusedImage: null,
  splashShownAt: null,
  splashHideScheduled: false,
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  if (elements.splashScreen) {
    document.body.classList.add("splash-active");
  }

  state.splashShownAt = performance.now();
  state.knownIds = loadKnown();
  attachEventListeners();

  try {
    await loadQuestions();
    updateProgressLabels();
    pickNextQuestion();
  } catch (error) {
    console.error(error);
    setStatus("Die Fragen konnten nicht geladen werden. Bitte starte einen lokalen Webserver (z.&nbsp;B. <code>python -m http.server</code>).", true);
  } finally {
    scheduleSplashHide();
  }
}

function attachEventListeners() {
  elements.filterMode.addEventListener("change", () => {
    state.mode = elements.filterMode.value;
    pickNextQuestion();
  });

  elements.markKnown.addEventListener("click", () => {
    if (!state.currentQuestion) return;
    state.knownIds.add(state.currentQuestion.id);
    persistKnown();
    updateProgressLabels();
    pickNextQuestion();
  });

  elements.markUnknown.addEventListener("click", () => {
    if (!state.currentQuestion) return;
    state.knownIds.delete(state.currentQuestion.id);
    persistKnown();
    updateProgressLabels();
    setStatus("Als unbekannt markiert. Weiter geht's!", false);
  });

  elements.nextQuestion.addEventListener("click", () => {
    pickNextQuestion();
  });

  elements.jumpToQuestion.addEventListener("click", () => {
    handleJumpRequest();
  });

  elements.questionNumberInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleJumpRequest();
    }
  });

  elements.resetProgress.addEventListener("click", () => {
    if (confirm("Möchtest du deinen Lernfortschritt wirklich löschen?")) {
      state.knownIds.clear();
      persistKnown();
      updateProgressLabels();
      setStatus("Fortschritt gelöscht.", false);
      pickNextQuestion();
    }
  });

  if (elements.imageWrapper) {
    elements.imageWrapper.addEventListener("click", handleImageClick);
    elements.imageWrapper.addEventListener("keydown", handleImageKeydown);
  }

  if (elements.closeLightbox) {
    elements.closeLightbox.addEventListener("click", () => closeImageLightbox());
  }

  if (elements.imageLightbox) {
    elements.imageLightbox.addEventListener("click", (event) => {
      if (event.target === elements.imageLightbox) {
        closeImageLightbox();
      }
    });
  }

  document.addEventListener("keydown", handleGlobalKeydown);

  elements.answers.addEventListener("click", (event) => {
    if (!state.currentQuestion) return;

    const item = event.target.closest("li[data-index]");
    if (!item) return;

    const answerIndex = Number.parseInt(item.dataset.index, 10);
    if (Number.isNaN(answerIndex)) return;

    if (state.isQuestionSolved) {
      return;
    }

    state.selectedAnswerIndex = answerIndex;
    highlightSelectedAnswer();
    evaluateAnswerSelection(answerIndex, item);
  });
}

async function loadQuestions() {
  const response = await fetch("data/questions.json");
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const payload = await response.json();
  state.questions = payload.questions ?? [];

  if (!state.questions.length) {
    throw new Error("Keine Fragen gefunden");
  }
}

function pickNextQuestion() {
  if (!state.questions.length) return;

  const available = filteredQuestions();
  let infoMessage = "";

  if (state.mode === "unknown") {
    const total = state.questions.length;
    const known = state.knownIds.size;
    if (total && known >= total) {
      infoMessage = "Alle Fragen sind als gelernt markiert. Wiederhole zur Festigung!";
    }
  }

  if (!available.length) {
    if (state.mode === "unknown") {
      setStatus("Alle Fragen sind als gelernt markiert. Gute Arbeit!", false);
    } else if (state.mode === "known") {
      setStatus("Du hast noch keine Frage als gelernt markiert.", false);
    }
    state.currentQuestion = null;
    elements.card.hidden = true;
    return;
  }

  const randomIndex = Math.floor(Math.random() * available.length);
  showQuestion(available[randomIndex], infoMessage);
}

function filteredQuestions() {
  if (state.mode === "all") {
    return [...state.questions];
  }

  if (state.mode === "known") {
    return state.questions.filter((question) => state.knownIds.has(question.id));
  }

  // unknown default
  const unknown = state.questions.filter((question) => !state.knownIds.has(question.id));
  return unknown.length ? unknown : [...state.questions];
}

function renderQuestion() {
  const question = state.currentQuestion;
  if (!question) {
    elements.card.hidden = true;
    return;
  }

  const part = question.section?.part;
  const topic = question.section?.topic;
  const parts = [part, topic].filter(Boolean).join(" · ");
  elements.sectionInfo.textContent = parts;
  elements.sectionInfo.hidden = !parts;

  elements.questionNumber.textContent = question.display_number;
  elements.questionPages.textContent = question.pages?.length ? `Seite ${question.pages.join(", ")}` : "";
  elements.questionText.textContent = question.question;

  elements.answers.innerHTML = "";
  question.answers.forEach((answer, index) => {
    const li = document.createElement("li");
    li.className = "answer-option";
    li.dataset.index = String(index);
    const key = document.createElement("span");
    key.className = "answer-key";
    key.textContent = String.fromCharCode(65 + index);

    const text = document.createElement("span");
    text.className = "answer-text";
    text.textContent = answer.text;

    li.append(key, text);
    elements.answers.append(li);
  });

  highlightSelectedAnswer();
  renderImages(question.images ?? []);
}

function renderImages(imagePaths) {
  elements.imageWrapper.innerHTML = "";

  if (!imagePaths.length) {
    elements.imageWrapper.hidden = true;
    return;
  }

  elements.imageWrapper.hidden = false;

  imagePaths.forEach((relativePath, index) => {
    const img = document.createElement("img");
    img.src = `data/${relativePath}`;
    img.alt = `Abbildung ${index + 1} zur Frage`;
    img.dataset.fullSrc = img.src;
    img.dataset.fullAlt = img.alt;
    img.loading = "lazy";
    img.decoding = "async";
    img.tabIndex = 0;
    elements.imageWrapper.append(img);
  });
}

function highlightSelectedAnswer() {
  const children = elements.answers.querySelectorAll(".answer-option");
  children.forEach((child) => {
    child.classList.toggle("selected", Number(child.dataset.index) === state.selectedAnswerIndex);
  });
}

function evaluateAnswerSelection(answerIndex, item) {
  const question = state.currentQuestion;
  const correctIndex = question?.correct_answer_index;

  if (typeof correctIndex !== "number") {
    setStatus("Für diese Frage liegt (noch) keine Lösung vor.", false);
    return;
  }

  if (state.isQuestionSolved) {
    return;
  }

  const isCorrect = answerIndex === correctIndex;
  if (isCorrect) {
    revealCorrectAnswer(correctIndex);
    const isFirstAttempt = state.attemptedAnswers.size === 0;
    state.isQuestionSolved = true;

    if (isFirstAttempt && !state.knownIds.has(question.id)) {
      state.knownIds.add(question.id);
      persistKnown();
      updateProgressLabels();
      setStatus("Richtig! Frage wurde als gelernt markiert.", false);
    } else {
      setStatus("Richtig!", false);
    }
  } else {
    item.classList.add("incorrect");
    state.attemptedAnswers.add(answerIndex);
    setStatus("Leider falsch. Versuche es erneut.", true);
  }
}

function revealCorrectAnswer(correctIndex) {
  const options = elements.answers.querySelectorAll(".answer-option");
  options.forEach((option, idx) => {
    option.classList.remove("selected");
    option.classList.toggle("correct", idx === correctIndex);
    if (idx === correctIndex) {
      option.classList.remove("incorrect");
    }
  });
}

function handleJumpRequest() {
  if (!state.questions.length) return;

  const rawValue = elements.questionNumberInput.value.trim();
  if (!rawValue) {
    setStatus("Bitte eine Fragennummer eingeben.", true);
    return;
  }

  const number = Number.parseInt(rawValue, 10);
  if (!Number.isInteger(number) || number < 1) {
    setStatus("Ungültige Fragennummer.", true);
    return;
  }

  const question = findQuestionByNumber(number);
  if (!question) {
    setStatus(`Keine Frage mit der Nummer ${number} gefunden.`, true);
    return;
  }

  elements.questionNumberInput.value = "";
  showQuestion(question, `Frage ${question.display_number} geladen.`);
}

function findQuestionByNumber(number) {
  return (
    state.questions.find((question) => question.question_number === number) ??
    state.questions.find((question) => question.id === number)
  );
}

function showQuestion(question, message = "") {
  closeImageLightbox({ suppressFocus: true });
  state.currentQuestion = question;
  state.selectedAnswerIndex = null;
  state.attemptedAnswers = new Set();
  state.isQuestionSolved = false;
  renderQuestion();
  elements.card.hidden = false;
  let statusMessage = message;
  if (!statusMessage && typeof question.correct_answer_index !== "number") {
    statusMessage = "Für diese Frage liegt (noch) keine Lösung vor.";
  }
  setStatus(statusMessage, false);
}

function loadKnown() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return new Set();
    }
    const list = JSON.parse(raw);
    if (Array.isArray(list)) {
      return new Set(list);
    }
  } catch (error) {
    console.warn("Konnte gespeicherte Daten nicht laden", error);
  }
  return new Set();
}

function persistKnown() {
  const payload = JSON.stringify([...state.knownIds]);
  localStorage.setItem(STORAGE_KEY, payload);
}

function updateProgressLabels() {
  const known = state.knownIds.size;
  const total = state.questions.length;
  const unknown = total - known;
  const percentage = total ? Math.round((known / total) * 100) : 0;
  const solutions = state.questions.reduce((count, question) => (
    typeof question.correct_answer_index === "number" ? count + 1 : count
  ), 0);

  elements.progressCount.textContent = `${known} / ${total} gelernt (${percentage}%)`;
  elements.unknownCount.textContent = `${unknown} offene Fragen`;
  elements.solutionCount.textContent = `${solutions} Lösungen hinterlegt`;
}

function setStatus(message, isError) {
  elements.status.innerHTML = message;
  elements.status.dataset.state = isError ? "error" : "info";
}

function handleImageClick(event) {
  const target = event.target.closest("img[data-full-src]");
  if (!target) {
    return;
  }
  state.lastFocusedImage = target;
  openImageLightbox(target.dataset.fullSrc, target.dataset.fullAlt || target.alt || "");
}

function handleImageKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const target = event.target.closest("img[data-full-src]");
  if (!target) {
    return;
  }
  event.preventDefault();
  state.lastFocusedImage = target;
  openImageLightbox(target.dataset.fullSrc, target.dataset.fullAlt || target.alt || "");
}

function handleGlobalKeydown(event) {
  if (event.key === "Escape") {
    closeImageLightbox();
  }
}

function openImageLightbox(src, alt) {
  if (!elements.imageLightbox || !elements.lightboxImage) {
    return;
  }

  elements.lightboxImage.src = src;
  elements.lightboxImage.alt = alt;
  elements.imageLightbox.hidden = false;
  document.body.classList.add("lightbox-open");

  if (elements.closeLightbox) {
    try {
      elements.closeLightbox.focus({ preventScroll: true });
    } catch (error) {
      elements.closeLightbox.focus();
    }
  }
}

function closeImageLightbox(options = {}) {
  const { suppressFocus = false } = options;
  if (!elements.imageLightbox || elements.imageLightbox.hidden) {
    state.lastFocusedImage = suppressFocus ? null : state.lastFocusedImage;
    return;
  }

  elements.imageLightbox.hidden = true;
  document.body.classList.remove("lightbox-open");

  if (elements.lightboxImage) {
    elements.lightboxImage.src = "";
    elements.lightboxImage.alt = "";
  }

  if (!suppressFocus && state.lastFocusedImage instanceof HTMLElement) {
    try {
      state.lastFocusedImage.focus({ preventScroll: true });
    } catch (error) {
      // ignore focus errors
    }
  }

  state.lastFocusedImage = null;
}

function scheduleSplashHide() {
  if (!elements.splashScreen) {
    document.body.classList.remove("splash-active");
    return;
  }

  if (state.splashHideScheduled) {
    return;
  }

  state.splashHideScheduled = true;
  const elapsed = typeof state.splashShownAt === "number" ? performance.now() - state.splashShownAt : 0;
  const remaining = Math.max(0, SPLASH_MIN_DURATION_MS - elapsed);
  window.setTimeout(hideSplashScreen, remaining);
}

function hideSplashScreen() {
  if (!elements.splashScreen) {
    document.body.classList.remove("splash-active");
    return;
  }

  if (elements.splashScreen.classList.contains("is-hidden")) {
    document.body.classList.remove("splash-active");
    return;
  }

  elements.splashScreen.classList.add("is-hidden");
  window.setTimeout(() => {
    if (elements.splashScreen) {
      elements.splashScreen.hidden = true;
    }
    document.body.classList.remove("splash-active");
  }, 400);
}
