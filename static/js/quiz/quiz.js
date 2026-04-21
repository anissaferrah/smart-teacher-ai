const SID = crypto.randomUUID();
const params = new URLSearchParams(location.search);
const ctx = {
  course_id: params.get('course_id') || '',
  chapter_index: params.get('chapter_index') || '0',
  section_index: params.get('section_index') || '0',
  chapter: params.get('chapter') || '',
  section_title: params.get('section_title') || '',
  slide_title: params.get('slide_title') || '',
  slide_content: params.get('slide_content') || '',
  slide_path: params.get('slide_path') || params.get('image_url') || '',
  course_title: params.get('course_title') || '',
  course_domain: params.get('course_domain') || '',
  language: params.get('language') || 'fr',
  level: params.get('level') || 'lycée',
};

let ws = null;
let wsReady = false;
let quizRequested = false;

function setStatus(text, tone=''){
  const badge = document.getElementById('statusBadge');
  const state = document.getElementById('quizState');
  if (badge) badge.textContent = text;
  if (state) state.textContent = text;
  if (badge) badge.style.borderColor = tone === 'good' ? 'rgba(0,229,176,.28)' : tone === 'bad' ? 'rgba(255,94,122,.3)' : 'rgba(124,109,250,.22)';
}

function send(payload){
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
}

function startSession(){
  const token = localStorage.getItem('token') || '';
  send({ type: 'start_session', language: ctx.language, level: ctx.level, token, course_id: ctx.course_id });
}

function buildQuizRequest(){
  return {
    type: 'quiz',
    course_id: ctx.course_id,
    chapter_index: Number(ctx.chapter_index || 0),
    section_index: Number(ctx.section_index || 0),
    chapter: ctx.chapter,
    section_title: ctx.section_title || ctx.slide_title,
    slide_title: ctx.slide_title,
    slide_content: ctx.slide_content,
    slide_path: ctx.slide_path,
    image_url: ctx.slide_path,
    language: ctx.language,
    level: ctx.level,
    course_title: ctx.course_title,
    course_domain: ctx.course_domain,
  };
}

function requestQuiz(){
  if (!wsReady) return;
  quizRequested = true;
  setStatus('Génération…');
  send(buildQuizRequest());
}

function connect(){
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${protocol}://${location.host}/ws/${SID}`);
  ws.onopen = () => {
    wsReady = true;
    setStatus('Connecté');
    startSession();
    if (!quizRequested) requestQuiz();
  };
  ws.onclose = () => {
    wsReady = false;
    setStatus('Reconnexion…');
    setTimeout(connect, 2500);
  };
  ws.onerror = () => setStatus('Erreur réseau', 'bad');
  ws.onmessage = ev => handle(JSON.parse(ev.data));
}

function fillContext(){
  const items = [
    ['Cours', ctx.course_title || 'Cours non renseigné'],
    ['Domaine', ctx.course_domain || 'Général'],
    ['Chapitre', ctx.chapter || '—'],
    ['Section', ctx.section_title || ctx.slide_title || '—'],
    ['Langue', ctx.language || 'fr'],
    ['Niveau', ctx.level || 'lycée'],
  ];
  document.getElementById('courseBadge').textContent = ctx.course_title || 'Quiz sans cours';
  document.getElementById('contextGrid').innerHTML = items.map(([label, value]) => `
    <div class="context-card">
      <div class="context-label">${label}</div>
      <div class="context-value">${String(value)}</div>
    </div>
  `).join('');
}

function renderQuizPrompt(area, quiz, titleFallback='Quiz'){
  if(!area) return null;
  const payload = quiz && typeof quiz === 'object' ? quiz : {};
  area.innerHTML = '';

  const card = document.createElement('div');
  card.className = 'quiz-card';

  const top = document.createElement('div');
  top.className = 'quiz-top';

  const tag = document.createElement('div');
  tag.className = 'quiz-tag';
  tag.textContent = 'Quiz';
  top.appendChild(tag);

  const title = document.createElement('div');
  title.className = 'quiz-title';
  title.textContent = String(payload.title || titleFallback || 'Quiz').trim();
  top.appendChild(title);

  const metaBits = [];
  if(payload.topic) metaBits.push(String(payload.topic).trim());
  if(payload.difficulty) metaBits.push(`Niveau: ${String(payload.difficulty).trim()}`);
  const questionCount = Array.isArray(payload.questions) ? payload.questions.length : Number(payload.question_count || 0);
  if(questionCount) metaBits.push(`${questionCount} question${questionCount > 1 ? 's' : ''}`);
  if(payload.chapter_title || payload.section_title){
    const parts = [];
    if(payload.chapter_title) parts.push(String(payload.chapter_title).trim());
    if(payload.section_title) parts.push(String(payload.section_title).trim());
    if(parts.length) metaBits.push(parts.join(' / '));
  }
  if(metaBits.length){
    const meta = document.createElement('div');
    meta.className = 'quiz-meta';
    meta.textContent = metaBits.join(' • ');
    top.appendChild(meta);
  }
  card.appendChild(top);

  const questions = Array.isArray(payload.questions) ? payload.questions : [];
  if(!questions.length){
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'Aucune question n'a encore été générée.';
    card.appendChild(empty);
    area.appendChild(card);
    return card;
  }

  const list = document.createElement('div');
  list.className = 'quiz-list';

  questions.forEach((question, index) => {
    const block = document.createElement('div');
    block.className = 'quiz-question';

    const heading = document.createElement('div');
    heading.className = 'quiz-question-title';
    const questionText = String(question?.question || question?.prompt || '').trim();
    heading.textContent = `${index + 1}. ${questionText || 'Question'}`;
    block.appendChild(heading);

    const optionsRaw = Array.isArray(question?.options) ? question.options : Array.isArray(question?.choices) ? question.choices : [];
    const options = optionsRaw.map(option => String(option).trim()).filter(Boolean);
    const explanation = String(question?.explanation || question?.feedback || '').trim();
    const practicalPrompt = String(question?.practical || question?.exercise || '').trim();
    const practicalAnswer = String(question?.practical_answer || question?.model_answer || '').trim();

    const resultBox = document.createElement('div');
    resultBox.className = 'quiz-result';
    resultBox.hidden = true;

    const resultTitle = document.createElement('div');
    resultTitle.className = 'quiz-result-title';
    resultTitle.textContent = 'Réponse et pratique';
    resultBox.appendChild(resultTitle);

    const answerLine = document.createElement('div');
    answerLine.className = 'quiz-result-line';
    resultBox.appendChild(answerLine);

    const practicalLine = document.createElement('div');
    practicalLine.className = 'quiz-result-line';
    resultBox.appendChild(practicalLine);

    const setResult = (tone, answerText, practicalText) => {
      resultBox.hidden = false;
      resultBox.className = `quiz-result ${tone}`;
      answerLine.textContent = answerText;
      practicalLine.textContent = practicalText;
    };

    if(options.length){
      const optionsWrap = document.createElement('div');
      optionsWrap.className = 'quiz-options';
      let correctIndex = Number(question?.correct_index ?? question?.answer_index ?? 0);
      if(!Number.isFinite(correctIndex)) correctIndex = 0;
      correctIndex = Math.max(0, Math.min(options.length - 1, Math.trunc(correctIndex)));

      options.forEach((optionText, optionIndex) => {
        const optionButton = document.createElement('button');
        optionButton.type = 'button';
        optionButton.className = 'quiz-option';
        optionButton.textContent = optionText;
        optionButton.onclick = () => {
          Array.from(optionsWrap.children).forEach(child => {
            child.disabled = true;
            child.classList.remove('correct', 'wrong');
          });
          optionButton.classList.add(optionIndex === correctIndex ? 'correct' : 'wrong');
          const correctOption = options[correctIndex];
          if(optionIndex === correctIndex){
            setResult(
              'good',
              `Réponse: ${explanation || correctOption || 'Bonne réponse.'}`,
              `Pratique: ${practicalPrompt || practicalAnswer || explanation || correctOption || 'Appliquer cette idée à un cas concret.'}`
            );
          }else{
            setResult(
              'bad',
              `Réponse attendue: ${correctOption}`,
              `Pratique: ${practicalPrompt || practicalAnswer || explanation || 'Relire la notion puis l'appliquer à un exemple.'}`
            );
          }
        };
        optionsWrap.appendChild(optionButton);
      });

      block.appendChild(optionsWrap);
    }else{
      setResult(
        'good',
        `Réponse: ${explanation || practicalAnswer || 'Question ouverte.'}`,
        `Pratique: ${practicalPrompt || practicalAnswer || explanation || 'Donner un exemple concret d'application.'}`
      );
    }

    if(practicalPrompt || practicalAnswer || explanation){
      resultBox.hidden = false;
      if(!resultBox.className.includes('good') && !resultBox.className.includes('bad')){
        resultBox.className = 'quiz-result';
      }
      if(!answerLine.textContent){
        answerLine.textContent = `Réponse: ${explanation || practicalAnswer || 'Bonne réponse.'}`;
      }
      if(!practicalLine.textContent){
        practicalLine.textContent = `Pratique: ${practicalPrompt || practicalAnswer || explanation || 'Appliquer cette idée à un cas concret.'}`;
      }
    }

    block.appendChild(resultBox);
    list.appendChild(block);
  });

  card.appendChild(list);
  area.appendChild(card);
  return card;
}

function handle(message){
  if(message.type === 'quiz_prompt'){
    setStatus('Quiz prêt', 'good');
    renderQuizPrompt(document.getElementById('quizHost'), message.quiz || {}, message.question || 'Quiz');
  }else if(message.type === 'state_change'){
    setStatus(message.display_message || message.state_name || 'Mise à jour');
  }else if(message.type === 'system_notice'){
    setStatus(message.text || 'Notice');
  }else if(message.type === 'error'){
    setStatus(message.message || 'Erreur', 'bad');
  }
}

fillContext();
connect();
