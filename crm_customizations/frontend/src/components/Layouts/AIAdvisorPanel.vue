<template>
  <div>
    <!-- Floating Expand Button (Visible when panel is closed) -->
    <button
      v-if="!isOpen"
      @click="togglePanel"
      class="fixed bottom-6 right-6 z-40 flex items-center justify-center w-14 h-14 rounded-full shadow-xl hover:shadow-2xl hover:scale-105 active:scale-95 transition-all duration-300 group focus:outline-none focus:ring-2 focus:ring-purple-400 ai-floating-btn"
      title="Open AI Advisor"
    >
      <!-- Sparkles / Chat Icon -->
      <svg class="w-6 h-6 group-hover:rotate-12 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 21l-.813-5.096L3 15l5.096-.813L9 9l.813 5.187L15 15l-5.187.904zM18 10.5l-.5-3.5-3.5-.5.5-3.5 3.5.5.5-3.5 3.5.5-.5 3.5-3.5.5z" />
      </svg>
      <span class="absolute -top-1 -right-1 flex h-3 w-3">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
        <span class="relative inline-flex rounded-full h-3 w-3 bg-purple-500"></span>
      </span>
    </button>

    <!-- Slide-in Right Side Panel -->
    <div
      :class="[
        'fixed top-0 right-0 h-screen z-50 bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800 shadow-2xl flex flex-col transition-all duration-300 ease-in-out',
        isOpen ? 'w-96 translate-x-0' : 'w-0 translate-x-full pointer-events-none'
      ]"
    >
      <!-- Panel Header -->
      <div class="flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-800 bg-gradient-to-r from-indigo-50/50 to-purple-50/50 dark:from-indigo-950/20 dark:to-purple-950/20">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-indigo-600 dark:text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" style="color: #6366f1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 21l-.813-5.096L3 15l5.096-.813L9 9l.813 5.187L15 15l-5.187.904z" />
          </svg>
          <h3 class="text-md font-semibold text-gray-900 dark:text-white">AI Advisor</h3>
        </div>
        <div class="flex items-center gap-1.5">
          <!-- Clear Chat -->
          <button
            @click="clearChat"
            class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 transition-colors"
            title="Clear Chat"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
          <!-- Close Button -->
          <button
            @click="togglePanel"
            class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Messages Area -->
      <div ref="chatContainer" class="flex-1 overflow-y-auto p-4 space-y-4 no-scrollbar">
        <!-- Welcome Message -->
        <div class="flex gap-2">
          <div class="w-8 h-8 rounded-full text-xs font-bold shrink-0 shadow-sm flex items-center justify-center ai-avatar">
            AI
          </div>
          <div class="flex flex-col gap-1 max-w-[80%]">
            <div class="bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 text-sm p-3 rounded-2xl rounded-tl-none shadow-sm animate-fade-in">
              Hello! I am your AI Advisor. Ask me anything about your CRM database (leads, deals, status counts, follow-up tasks, etc.).
            </div>
            <span class="text-[10px] text-gray-400 px-1">Just now</span>
          </div>
        </div>

        <!-- Render Messages -->
        <div
          v-for="(msg, index) in messages"
          :key="index"
          :class="['flex gap-2', msg.sender === 'user' ? 'justify-end' : 'justify-start']"
        >
          <!-- AI Avatar -->
          <div
            v-if="msg.sender === 'ai'"
            class="w-8 h-8 rounded-full text-xs font-bold shrink-0 shadow-sm flex items-center justify-center ai-avatar"
          >
            AI
          </div>

          <div class="flex flex-col gap-1 max-w-[80%]">
            <div
              :class="[
                'text-sm p-3 rounded-2xl shadow-sm leading-relaxed whitespace-pre-wrap',
                msg.sender === 'user'
                  ? 'bg-gradient-to-tr from-indigo-600 to-purple-600 text-white rounded-tr-none'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded-tl-none'
              ]"
              :style="msg.sender === 'user' ? 'background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important' : ''"
            >
              {{ msg.text }}
            </div>
            <span :class="['text-[10px] text-gray-400 px-1', msg.sender === 'user' ? 'text-right' : 'text-left']">
              {{ msg.time }}
            </span>
          </div>
        </div>

        <!-- Typing Indicator -->
        <div v-if="loading" class="flex gap-2">
          <div class="w-8 h-8 rounded-full text-xs font-bold shrink-0 shadow-sm animate-pulse flex items-center justify-center ai-avatar">
            AI
          </div>
          <div class="bg-gray-100 dark:bg-gray-800 p-3 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-1">
            <span class="w-2.5 h-2.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce" style="animation-delay: 0ms"></span>
            <span class="w-2.5 h-2.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce" style="animation-delay: 150ms"></span>
            <span class="w-2.5 h-2.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce" style="animation-delay: 300ms"></span>
          </div>
        </div>
      </div>

      <!-- Quick Action Suggestions -->
      <div v-if="messages.length === 0" class="px-4 py-3 border-t border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-900/50">
        <p class="text-xs font-medium text-gray-400 mb-2">Suggested Queries:</p>
        <div class="flex flex-col gap-1.5 pb-2">
          <button
            v-for="(suggestion, i) in suggestions"
            :key="i"
            @click="askAdvisor(suggestion)"
            class="suggestion-btn text-xs px-3 py-2 rounded-xl text-left transition-colors duration-150 cursor-pointer block select-none border focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {{ suggestion }}
          </button>
        </div>
      </div>

      <!-- Input Area -->
      <form @submit.prevent="submitQuery" class="p-3 border-t border-gray-100 dark:border-gray-800 flex gap-2 items-center bg-white dark:bg-gray-900">
        <input
          v-model="queryInput"
          type="text"
          placeholder="Ask AI Advisor..."
          class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent dark:bg-gray-800 dark:text-white"
          :disabled="loading"
        />
        <button
          type="submit"
          class="p-2 rounded-xl text-white shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50 transition-all duration-150 ai-send-btn"
          :disabled="loading || !queryInput.trim()"
        >
          <svg class="w-4 h-4 transform rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { call } from 'frappe-ui'

const isOpen = ref(false)
const queryInput = ref('')
const loading = ref(false)
const messages = ref([])
const chatContainer = ref(null)

const suggestions = [
  'How many follow-ups has been left to do?',
  'How many leads has been contacted, nurtured, or converted?',
  'What is our lead status breakdown?',
  'Give me a summary of deals currently in play.'
]

function togglePanel() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    nextTick(() => {
      scrollToBottom()
    })
  }
}

function clearChat() {
  messages.value = []
}

function submitQuery() {
  const query = queryInput.value.trim()
  if (!query) return
  queryInput.value = ''
  askAdvisor(query)
}

function askAdvisor(queryText) {
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  messages.value.push({ sender: 'user', text: queryText, time })
  
  loading.value = true
  nextTick(() => {
    scrollToBottom()
  })

  call('ai_crm.api.chat_query', { query: queryText })
    .then((res) => {
      const responseText = res && res.response 
        ? res.response 
        : 'I apologize, I received an invalid response from the advisor engine.'
      
      messages.value.push({
        sender: 'ai',
        text: responseText,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      })
    })
    .catch((err) => {
      messages.value.push({
        sender: 'ai',
        text: 'Sorry, I encountered an error connecting to the AI models: ' + (err.messages?.[0] || err.message || 'Unknown network error'),
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      })
    })
    .finally(() => {
      loading.value = false
      nextTick(() => {
        scrollToBottom()
      })
    })
}

function scrollToBottom() {
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}
</script>

<style scoped>
/* Hidden scrollbar */
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;  /* IE and Edge */
  scrollbar-width: none;  /* Firefox */
}

/* Floating expand button style */
.ai-floating-btn {
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important;
  color: white !important;
}

.ai-floating-btn:hover {
  background: linear-gradient(135deg, #4f46e5 0%, #9333ea 100%) !important;
  transform: scale(1.05);
}

/* AI Avatar styles */
.ai-avatar {
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important;
  color: white !important;
}

/* Send button style */
.ai-send-btn {
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important;
  color: white !important;
}

.ai-send-btn:hover {
  background: linear-gradient(135deg, #4f46e5 0%, #9333ea 100%) !important;
}

.suggestion-btn {
  color: #4f46e5 !important;
  background-color: #f5f3ff !important;
  border-color: rgba(224, 231, 255, 0.5) !important;
}

.suggestion-btn:hover {
  background-color: #ede9fe !important;
}

:global(.dark) .suggestion-btn {
  color: #a5b4fc !important;
  background-color: rgba(30, 27, 75, 0.4) !important;
  border-color: rgba(49, 46, 129, 0.3) !important;
}

:global(.dark) .suggestion-btn:hover {
  background-color: rgba(49, 46, 129, 0.6) !important;
}
</style>
