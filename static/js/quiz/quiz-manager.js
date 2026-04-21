/**
 * Quiz Manager - Handles pagination and step-by-step quiz flow
 * Replaces full-scroll quiz with single-question-per-view interface
 */

class QuizManager {
  constructor(containerId = "quiz-container") {
    this.container = document.getElementById(containerId);
    this.currentQuestionIndex = 0;
    this.quiz = null;
    this.userAnswers = [];
    this.startTime = null;
    this.questionStartTimes = [];
  }

  /**
   * Load quiz data and initialize UI
   * @param {Object} quizData - Quiz object with questions array
   */
  loadQuiz(quizData) {
    this.quiz = quizData;
    this.currentQuestionIndex = 0;
    this.userAnswers = new Array(quizData.questions.length).fill(null);
    this.questionStartTimes = new Array(quizData.questions.length).fill(null);
    this.startTime = Date.now();
    this.renderQuestion();
  }

  /**
   * Render current question (single question view)
   */
  renderQuestion() {
    if (!this.quiz || this.currentQuestionIndex >= this.quiz.questions.length) {
      this.renderCompleted();
      return;
    }

    const question = this.quiz.questions[this.currentQuestionIndex];
    const progress = this.currentQuestionIndex + 1;
    const total = this.quiz.questions.length;

    this.questionStartTimes[this.currentQuestionIndex] = Date.now();

    const html = `
      <div class="quiz-header">
        <h2 class="quiz-title">${this.quiz.title || "Quiz"}</h2>
        <div class="quiz-progress">
          <div class="progress-bar">
            <div class="progress-fill" style="width: ${(progress / total) * 100}%"></div>
          </div>
          <p class="progress-text">Question ${progress}/${total}</p>
        </div>
      </div>

      <div class="quiz-question-container">
        <div class="question-content">
          <h3 class="question-text">${this.escapeHtml(question.question)}</h3>
          <p class="question-difficulty">Difficulté: ${question.difficulty || "Normal"}</p>
        </div>

        <div class="question-options">
          ${question.options
            .map(
              (option, idx) => `
            <button class="option-button ${
              this.userAnswers[this.currentQuestionIndex] === idx
                ? "selected"
                : ""
            }" 
              data-index="${idx}"
              onclick="quizManager.selectAnswer(${idx})">
              <span class="option-letter">${String.fromCharCode(65 + idx)}</span>
              <span class="option-text">${this.escapeHtml(option)}</span>
            </button>
          `
            )
            .join("")}
        </div>
      </div>

      <div class="quiz-navigation">
        <button class="btn-prev" onclick="quizManager.previousQuestion()" 
          ${progress === 1 ? "disabled" : ""}>
          ← Précédent
        </button>
        <button class="btn-next" onclick="quizManager.nextQuestion()" 
          ${this.userAnswers[this.currentQuestionIndex] === null ? "disabled" : ""}>
          Suivant →
        </button>
      </div>
    `;

    this.container.innerHTML = html;
  }

  /**
   * Select answer for current question
   * @param {number} optionIndex - Index of selected option (0-3)
   */
  selectAnswer(optionIndex) {
    this.userAnswers[this.currentQuestionIndex] = optionIndex;
    this.renderQuestion();
  }

  /**
   * Move to next question
   */
  nextQuestion() {
    if (this.currentQuestionIndex < this.quiz.questions.length - 1) {
      this.currentQuestionIndex++;
      this.renderQuestion();
    }
  }

  /**
   * Move to previous question
   */
  previousQuestion() {
    if (this.currentQuestionIndex > 0) {
      this.currentQuestionIndex--;
      this.renderQuestion();
    }
  }

  /**
   * Render completion screen with results
   */
  renderCompleted() {
    const results = this.calculateResults();
    const totalTime = Math.round((Date.now() - this.startTime) / 1000);

    const html = `
      <div class="quiz-completed">
        <h2>Quiz Terminé! 🎉</h2>
        
        <div class="quiz-results">
          <div class="result-card">
            <p class="result-label">Score</p>
            <p class="result-value">${results.correct}/${results.total}</p>
          </div>
          
          <div class="result-card">
            <p class="result-label">Pourcentage</p>
            <p class="result-value">${results.percentage}%</p>
          </div>
          
          <div class="result-card">
            <p class="result-label">Temps</p>
            <p class="result-value">${Math.floor(totalTime / 60)}:${String(totalTime % 60).padStart(2, "0")}</p>
          </div>
        </div>

        <div class="quiz-detail-results">
          <h3>Résultats par question</h3>
          ${this.quiz.questions
            .map((q, idx) => {
              const isCorrect = this.userAnswers[idx] === q.correct_index;
              return `
                <div class="result-item ${isCorrect ? "correct" : "incorrect"}">
                  <div class="result-icon">${isCorrect ? "✓" : "✗"}</div>
                  <div class="result-text">
                    <p class="result-q">Q${idx + 1}: ${this.escapeHtml(q.question)}</p>
                    <p class="result-a">Votre réponse: ${this.escapeHtml(q.options[this.userAnswers[idx]] || "Non répondu")}</p>
                    ${!isCorrect ? `<p class="result-correct">Correcte: ${this.escapeHtml(q.options[q.correct_index])}</p>` : ""}
                    ${q.explanation ? `<p class="result-explanation">${this.escapeHtml(q.explanation)}</p>` : ""}
                  </div>
                </div>
              `;
            })
            .join("")}
        </div>

        <div class="quiz-actions">
          <button class="btn-primary" onclick="quizManager.restart()">Recommencer</button>
          <button class="btn-secondary" onclick="quizManager.close()">Fermer</button>
        </div>
      </div>
    `;

    this.container.innerHTML = html;
  }

  /**
   * Calculate quiz results
   * @returns {Object} Results object with correct, total, percentage
   */
  calculateResults() {
    let correct = 0;
    this.quiz.questions.forEach((q, idx) => {
      if (this.userAnswers[idx] === q.correct_index) {
        correct++;
      }
    });
    return {
      correct,
      total: this.quiz.questions.length,
      percentage: Math.round((correct / this.quiz.questions.length) * 100),
    };
  }

  /**
   * Restart quiz
   */
  restart() {
    this.loadQuiz(this.quiz);
  }

  /**
   * Close quiz
   */
  close() {
    this.container.innerHTML = "";
  }

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const map = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return text.replace(/[&<>"']/g, (m) => map[m]);
  }
}

// Global instance for HTML onclick handlers
let quizManager = new QuizManager("quiz-container");
