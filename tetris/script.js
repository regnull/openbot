const COLS = 10;
const ROWS = 20;
const BLOCK = 30;
const NEXT_BLOCK = 24;
const LINE_POINTS = [0, 100, 300, 500, 800];

const SHAPES = {
  I: [[1, 1, 1, 1]],
  J: [[1, 0, 0], [1, 1, 1]],
  L: [[0, 0, 1], [1, 1, 1]],
  O: [[1, 1], [1, 1]],
  S: [[0, 1, 1], [1, 1, 0]],
  T: [[0, 1, 0], [1, 1, 1]],
  Z: [[1, 1, 0], [0, 1, 1]],
};

const COLORS = { I: '#75f1ff', J: '#5d7cff', L: '#ffae42', O: '#ffe45e', S: '#73ff8f', T: '#c86bff', Z: '#ff5d77' };

const boardCanvas = document.querySelector('#board');
const boardContext = boardCanvas.getContext('2d');
const nextCanvas = document.querySelector('#next');
const nextContext = nextCanvas.getContext('2d');
const scoreElement = document.querySelector('#score');
const linesElement = document.querySelector('#lines');
const levelElement = document.querySelector('#level');
const statusElement = document.querySelector('#status');
const restartButton = document.querySelector('#restart');
const overlay = document.querySelector('#overlay');

let board;
let currentPiece;
let nextPiece;
let score;
let lines;
let level;
let dropInterval;
let dropCounter;
let lastTime;
let animationFrame;
let running = false;
let paused = false;
let gameOver = false;

function createBoard() {
  return Array.from({ length: ROWS }, () => Array(COLS).fill(null));
}

function randomPiece() {
  const types = Object.keys(SHAPES);
  const type = types[Math.floor(Math.random() * types.length)];
  const matrix = SHAPES[type].map(row => [...row]);
  return { type, matrix, x: Math.floor((COLS - matrix[0].length) / 2), y: 0 };
}

function resetGame() {
  board = createBoard();
  score = 0;
  lines = 0;
  level = 1;
  dropInterval = 900;
  dropCounter = 0;
  lastTime = 0;
  running = true;
  paused = false;
  gameOver = false;
  currentPiece = randomPiece();
  nextPiece = randomPiece();
  updateHud();
  setOverlay('', '', true);
  cancelAnimationFrame(animationFrame);
  animationFrame = requestAnimationFrame(update);
}

function update(time = 0) {
  if (!running) return;
  const deltaTime = time - lastTime;
  lastTime = time;
  if (!paused) {
    dropCounter += deltaTime;
    if (dropCounter > dropInterval) moveDown();
  }
  draw();
  animationFrame = requestAnimationFrame(update);
}

function draw() {
  drawBoard();
  drawPiece(boardContext, currentPiece, BLOCK);
  drawNext();
}

function drawBoard() {
  boardContext.clearRect(0, 0, boardCanvas.width, boardCanvas.height);
  boardContext.fillStyle = '#050816';
  boardContext.fillRect(0, 0, boardCanvas.width, boardCanvas.height);
  drawGrid();
  board.forEach((row, y) => row.forEach((type, x) => {
    if (type) drawBlock(boardContext, x, y, BLOCK, COLORS[type]);
  }));
}

function drawGrid() {
  boardContext.strokeStyle = 'rgba(255, 255, 255, 0.045)';
  boardContext.lineWidth = 1;
  for (let x = 0; x <= COLS; x++) {
    boardContext.beginPath();
    boardContext.moveTo(x * BLOCK, 0);
    boardContext.lineTo(x * BLOCK, ROWS * BLOCK);
    boardContext.stroke();
  }
  for (let y = 0; y <= ROWS; y++) {
    boardContext.beginPath();
    boardContext.moveTo(0, y * BLOCK);
    boardContext.lineTo(COLS * BLOCK, y * BLOCK);
    boardContext.stroke();
  }
}

function drawPiece(context, piece, size, offsetX = 0, offsetY = 0) {
  if (!piece) return;
  piece.matrix.forEach((row, y) => row.forEach((value, x) => {
    if (value) drawBlock(context, piece.x + x + offsetX, piece.y + y + offsetY, size, COLORS[piece.type]);
  }));
}

function drawBlock(context, x, y, size, color) {
  const px = x * size;
  const py = y * size;
  const padding = Math.max(2, size * 0.08);
  context.fillStyle = color;
  context.shadowBlur = 14;
  context.shadowColor = color;
  context.fillRect(px + padding, py + padding, size - padding * 2, size - padding * 2);
  context.shadowBlur = 0;
  const gradient = context.createLinearGradient(px, py, px + size, py + size);
  gradient.addColorStop(0, 'rgba(255,255,255,0.38)');
  gradient.addColorStop(0.45, 'rgba(255,255,255,0.04)');
  gradient.addColorStop(1, 'rgba(0,0,0,0.22)');
  context.fillStyle = gradient;
  context.fillRect(px + padding, py + padding, size - padding * 2, size - padding * 2);
}

function drawNext() {
  nextContext.clearRect(0, 0, nextCanvas.width, nextCanvas.height);
  nextContext.fillStyle = '#050816';
  nextContext.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
  const preview = { ...nextPiece, x: (nextCanvas.width / NEXT_BLOCK - nextPiece.matrix[0].length) / 2, y: (nextCanvas.height / NEXT_BLOCK - nextPiece.matrix.length) / 2 };
  drawPiece(nextContext, preview, NEXT_BLOCK);
}

function moveDown() {
  currentPiece.y++;
  if (collides(currentPiece)) {
    currentPiece.y--;
    lockPiece();
    clearLines();
    spawnPiece();
  }
  dropCounter = 0;
}

function moveHorizontal(direction) {
  if (!canPlay()) return;
  currentPiece.x += direction;
  if (collides(currentPiece)) currentPiece.x -= direction;
  draw();
}

function rotatePiece() {
  if (!canPlay()) return;
  const originalMatrix = currentPiece.matrix;
  const originalX = currentPiece.x;
  currentPiece.matrix = rotateMatrix(currentPiece.matrix);
  for (const kick of [0, -1, 1, -2, 2]) {
    currentPiece.x = originalX + kick;
    if (!collides(currentPiece)) {
      draw();
      return;
    }
  }
  currentPiece.matrix = originalMatrix;
  currentPiece.x = originalX;
}

function rotateMatrix(matrix) {
  return matrix[0].map((_, index) => matrix.map(row => row[index]).reverse());
}

function hardDrop() {
  if (!running) {
    resetGame();
    return;
  }
  if (!canPlay()) return;
  let distance = 0;
  while (!collides(currentPiece)) {
    currentPiece.y++;
    distance++;
  }
  currentPiece.y--;
  score += Math.max(0, distance - 1) * 2;
  lockPiece();
  clearLines();
  spawnPiece();
  dropCounter = 0;
  updateHud();
  draw();
}

function collides(piece) {
  return piece.matrix.some((row, y) => row.some((value, x) => {
    if (!value) return false;
    const boardX = piece.x + x;
    const boardY = piece.y + y;
    return boardX < 0 || boardX >= COLS || boardY >= ROWS || (boardY >= 0 && board[boardY][boardX]);
  }));
}

function lockPiece() {
  currentPiece.matrix.forEach((row, y) => row.forEach((value, x) => {
    if (!value) return;
    const boardY = currentPiece.y + y;
    const boardX = currentPiece.x + x;
    if (boardY >= 0) board[boardY][boardX] = currentPiece.type;
  }));
}

function clearLines() {
  let cleared = 0;
  for (let y = ROWS - 1; y >= 0; y--) {
    if (board[y].every(Boolean)) {
      board.splice(y, 1);
      board.unshift(Array(COLS).fill(null));
      cleared++;
      y++;
    }
  }
  if (cleared > 0) {
    lines += cleared;
    score += LINE_POINTS[cleared] * level;
    level = Math.floor(lines / 10) + 1;
    dropInterval = Math.max(90, 900 - (level - 1) * 75);
    updateHud();
  }
}

function spawnPiece() {
  currentPiece = nextPiece;
  currentPiece.x = Math.floor((COLS - currentPiece.matrix[0].length) / 2);
  currentPiece.y = 0;
  nextPiece = randomPiece();
  if (collides(currentPiece)) endGame();
}

function endGame() {
  running = false;
  gameOver = true;
  cancelAnimationFrame(animationFrame);
  updateHud('Game Over');
  setOverlay('Game Over', 'Press Start or Space to try again', false);
  draw();
}

function togglePause() {
  if (!running || gameOver) return;
  paused = !paused;
  updateHud(paused ? 'Paused' : 'Playing');
  setOverlay(paused ? 'Paused' : '', paused ? 'Press P to resume' : '', !paused);
}

function canPlay() {
  return running && !paused && !gameOver;
}

function updateHud(forcedStatus) {
  scoreElement.textContent = score.toLocaleString();
  linesElement.textContent = lines.toLocaleString();
  levelElement.textContent = level.toLocaleString();
  statusElement.textContent = forcedStatus || (paused ? 'Paused' : running ? 'Playing' : gameOver ? 'Game Over' : 'Ready');
}

function setOverlay(title, message, hidden) {
  overlay.classList.toggle('hidden', hidden);
  if (!hidden) {
    overlay.querySelector('h2').textContent = title;
    overlay.querySelector('p').textContent = message;
  }
}

function handleKeydown(event) {
  if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Space'].includes(event.code)) event.preventDefault();
  switch (event.code) {
    case 'ArrowLeft': moveHorizontal(-1); break;
    case 'ArrowRight': moveHorizontal(1); break;
    case 'ArrowDown':
      if (canPlay()) {
        moveDown();
        score += 1;
        updateHud();
      }
      break;
    case 'ArrowUp':
    case 'KeyX': rotatePiece(); break;
    case 'Space': hardDrop(); break;
    case 'KeyP': togglePause(); break;
  }
}

restartButton.addEventListener('click', resetGame);
document.addEventListener('keydown', handleKeydown);

board = createBoard();
score = 0;
lines = 0;
level = 1;
dropInterval = 900;
currentPiece = randomPiece();
nextPiece = randomPiece();
updateHud('Ready');
draw();
