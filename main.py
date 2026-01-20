# filename: nix_ai_telegram_aiogram.py
import json
import os
import re
import random
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== STATES ====================

class DialogStates(StatesGroup):
    """Состояния диалога"""
    AWAITING_WEATHER_CITY = State()
    AWAITING_CORRECTION = State()
    AWAITING_REMEMBER = State()
    IN_CONVERSATION = State()

# ==================== DATA CLASSES ====================

@dataclass
class UserProfile:
    """Профиль пользователя"""
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    conversation_count: int = 0
    total_messages: int = 0
    learned_contributions: int = 0
    last_active: datetime = field(default_factory=datetime.now)
    preferences: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "conversation_count": self.conversation_count,
            "total_messages": self.total_messages,
            "learned_contributions": self.learned_contributions,
            "last_active": self.last_active.isoformat(),
            "preferences": self.preferences
        }
    
    @classmethod
    def from_dict(cls, data: Dict):
        return cls(
            user_id=data["user_id"],
            username=data.get("username"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            conversation_count=data.get("conversation_count", 0),
            total_messages=data.get("total_messages", 0),
            learned_contributions=data.get("learned_contributions", 0),
            last_active=datetime.fromisoformat(data.get("last_active", datetime.now().isoformat())),
            preferences=data.get("preferences", {})
        )

@dataclass
class WeatherConfig:
    """Конфигурация погодного сервиса"""
    api_key: str = ""
    base_url: str = "http://api.openweathermap.org/data/2.5/weather"
    units: str = "metric"
    lang: str = "ru"

# ==================== NIX AI CORE ====================

class NixAICore:
    """Ядро ИИ Nix AI с автообучением"""
    
    def __init__(self, knowledge_file: str = "knowledge.json"):
        self.knowledge_file = knowledge_file
        self.knowledge = self._load_knowledge()
        self.weather_config = WeatherConfig()
        self._load_weather_config()
        
        # Базовые правила
        self.rules = {
            r'привет|здравствуй|hello|hi|хай': self._greet,
            r'пока|прощай|до свидания|bye': self._goodbye,
            r'как дела|как ты|how are you': self._how_are_you,
            r'спасибо|благодарю|thanks': self._thank_you,
            r'твое имя|тебя зовут|who are you': self._about_me,
            r'создатель|кто создал|who created': self._about_creator,
            r'помощь|help|что ты умеешь': self._help,
            r'время|который час|time': self._time,
            r'дата|число|какое число': self._date,
            r'запомни|remember that': self._remember_info,
            r'что ты знаешь|расскажи о|что знаешь': self._recall_info,
            r'очисти память|забудь все': self._clear_memory,
            r'как учишься|как обучаешься': self._how_i_learn,
            r'погода|weather|прогноз': self._weather_handler,
            r'статистика|stats|моя статистика': self._stats_handler,
            r'курс валют|курс доллара|курс евро': self._currency_handler,
            r'новости|news|что нового': self._news_handler,
            r'анекдот|шутка|расскажи шутку': self._joke_handler,
        }
        
        # Состояния для обучения
        self.learning_modes = {
            'auto_correction': True,
            'ask_before_learning': False,
            'confidence_threshold': 0.3,
        }
        
        # Кэш для погоды (город -> (время, данные))
        self.weather_cache = {}
        self.cache_duration = timedelta(minutes=30)
    
    def _load_knowledge(self) -> Dict:
        """Загрузка базы знаний из JSON"""
        if os.path.exists(self.knowledge_file):
            try:
                with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки знаний: {e}")
                return self._create_default_knowledge()
        else:
            return self._create_default_knowledge()
    
    def _load_weather_config(self):
        """Загрузка конфигурации погоды"""
        config_file = "weather_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    self.weather_config = WeatherConfig(**config_data)
                    logger.info("Конфигурация погоды загружена")
            except Exception as e:
                logger.error(f"Ошибка загрузки конфигурации погоды: {e}")
    
    def _create_default_knowledge(self) -> Dict:
        """Создание базовой базы знаний"""
        default_knowledge = {
            "facts": {
                "создатель": "Меня создал Аслан",
                "имя": "Nix AI",
                "версия": "0.1 (Telegram Edition)",
                "цель": "Помогать людям в Telegram"
            },
            "memory": {},
            "learned_phrases": {},
            "statistics": {
                "total_conversations": 0,
                "total_messages": 0,
                "learned_qna": 0,
                "corrections_received": 0,
                "first_start": datetime.now().isoformat(),
                "total_users": 0
            },
            "qna": {
                "что такое python": "Python — это язык программирования",
                "что такое искусственный интеллект": "ИИ — это система, имитирующая человеческий интеллект",
                "как тебя зовут": "Меня зовут Nix AI",
                "кто создал тебя": "Меня создал разработчик, который хочет сделать полезного ИИ",
            },
            "user_profiles": {}
        }
        self._save_knowledge(default_knowledge)
        return default_knowledge
    
    def _save_knowledge(self, knowledge: Optional[Dict] = None):
        """Сохранение базы знаний"""
        if knowledge is None:
            knowledge = self.knowledge
            
        try:
            with open(self.knowledge_file, 'w', encoding='utf-8') as f:
                json.dump(knowledge, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения знаний: {e}")
    
    def get_or_create_user_profile(self, user_id: int, username: str = None, 
                                   first_name: str = None, last_name: str = None) -> UserProfile:
        """Получить или создать профиль пользователя"""
        user_profiles = self.knowledge.get("user_profiles", {})
        user_str = str(user_id)
        
        if user_str in user_profiles:
            profile_data = user_profiles[user_str]
            profile = UserProfile.from_dict(profile_data)
            # Обновляем данные если они изменились
            if username and username != profile.username:
                profile.username = username
            if first_name and first_name != profile.first_name:
                profile.first_name = first_name
            if last_name and last_name != profile.last_name:
                profile.last_name = last_name
        else:
            profile = UserProfile(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                conversation_count=1
            )
            self.knowledge["statistics"]["total_users"] = self.knowledge["statistics"].get("total_users", 0) + 1
        
        profile.last_active = datetime.now()
        self._save_user_profile(profile)
        return profile
    
    def _save_user_profile(self, profile: UserProfile):
        """Сохранить профиль пользователя"""
        if "user_profiles" not in self.knowledge:
            self.knowledge["user_profiles"] = {}
        
        self.knowledge["user_profiles"][str(profile.user_id)] = profile.to_dict()
        self._save_knowledge()
    
    def update_user_stats(self, user_id: int, field: str = "total_messages"):
        """Обновление статистики пользователя"""
        user_profiles = self.knowledge.get("user_profiles", {})
        user_str = str(user_id)
        
        if user_str in user_profiles:
            if field == "total_messages":
                self.knowledge["user_profiles"][user_str]["total_messages"] += 1
            elif field == "learned_contributions":
                self.knowledge["user_profiles"][user_str]["learned_contributions"] += 1
            elif field == "conversation_count":
                self.knowledge["user_profiles"][user_str]["conversation_count"] += 1
            
            self.knowledge["user_profiles"][user_str]["last_active"] = datetime.now().isoformat()
        
        # Обновляем общую статистику
        if field in self.knowledge["statistics"]:
            self.knowledge["statistics"][field] += 1
        
        self._save_knowledge()
    
    # ==================== БАЗОВЫЕ МЕТОДЫ ОТВЕТОВ ====================
    
    def _greet(self, message: str, user_profile: UserProfile = None) -> str:
        """Приветствие"""
        greetings = [
            "Привет! Я Nix AI, ваш цифровой помощник в Telegram! 👋",
            "Здравствуйте! Рад видеть вас здесь!",
            "Приветствую! Готов помочь вам с любыми вопросами.",
            "Привет! Как я могу вам помочь сегодня?"
        ]
        
        if user_profile:
            if user_profile.first_name:
                name_options = [
                    f"С возвращением, {user_profile.first_name}! Как ваши дела?",
                    f"Рад вас снова видеть, {user_profile.first_name}!",
                    f"Привет, {user_profile.first_name}! Чем могу помочь?"
                ]
                return random.choice(name_options)
        
        return random.choice(greetings)
    
    def _goodbye(self, message: str, user_profile: UserProfile = None) -> str:
        """Прощание"""
        farewells = [
            "До свидания! Буду рад помочь снова.",
            "Пока! Возвращайтесь, если понадобится помощь.",
            "Всего хорошего! 👋",
            "До встречи! Не забывайте меня!"
        ]
        
        if user_profile and user_profile.first_name:
            return f"Пока, {user_profile.first_name}! {random.choice(farewells)}"
        return random.choice(farewells)
    
    def _how_are_you(self, message: str, user_profile: UserProfile = None) -> str:
        """Ответ на вопрос о делах"""
        responses = [
            "У меня все отлично! Спасибо, что спросили. 😊",
            "Работаю в штатном режиме. Как ваши дела?",
            "Прекрасно! Готов помогать вам с любыми вопросами.",
            "Как у цифрового помощника, у меня всегда хорошо!"
        ]
        return random.choice(responses)
    
    def _thank_you(self, message: str, user_profile: UserProfile = None) -> str:
        """Ответ на благодарность"""
        responses = [
            "Всегда пожалуйста! 😊",
            "Рад был помочь!",
            "Обращайтесь ещё!",
            "Это моя работа в Telegram!"
        ]
        return random.choice(responses)
    
    def _about_me(self, message: str, user_profile: UserProfile = None) -> str:
        """Рассказ о себе"""
        facts = self.knowledge["facts"]
        return (f"🤖 Я {facts['имя']}, версия {facts['версия']}.\n"
                f"🎯 {facts['цель']}\n"
                f"💾 Создан на Python с использованием aiogram!\n"
                f"📚 Я учусь на каждом нашем диалоге.")
    
    def _about_creator(self, message: str, user_profile: UserProfile = None) -> str:
        """О создателе"""
        return self.knowledge["facts"]["создатель"]
    
    def _help(self, message: str, user_profile: UserProfile = None) -> str:
        """Помощь"""
        return """
🤖 *Nix AI - Telegram Edition*

📋 *Что я умею:*

• Приветствоваться и прощаться
• Отвечать на вопросы (и учиться, если не знаю ответа)
• Запоминать информацию
• Рассказывать о себе
• Показывать время и дату

🌤️ *Погода:*
Напиши "погода" или нажми кнопку, затем укажи город

💾 *Обучение:*
Если я не знаю ответа - я спрошу у вас и запомню правильный ответ

📊 *Статистика:*
Узнай сколько я уже знаю и сколько мы общались

🎮 *Дополнительно:*
• Курсы валют
• Анекдоты
• Новости (в разработке)

💡 *Просто общайтесь со мной - я научусь!*
        """
    
    def _time(self, message: str, user_profile: UserProfile = None) -> str:
        """Текущее время"""
        now = datetime.now()
        return f"🕐 Сейчас {now.strftime('%H:%M:%S')}"
    
    def _date(self, message: str, user_profile: UserProfile = None) -> str:
        """Текущая дата"""
        now = datetime.now()
        return f"📅 Сегодня {now.strftime('%d.%m.%Y')}"
    
    def _remember_info(self, message: str, user_profile: UserProfile = None) -> str:
        """Запоминание информации"""
        match = re.search(r'запомни\s*(?:что|,)?\s*(.+)', message.lower())
        if match:
            fact = match.group(1).strip()
            fact_key = fact[:50]
            
            if "learned_facts" not in self.knowledge:
                self.knowledge["learned_facts"] = {}
            
            self.knowledge["learned_facts"][fact_key] = {
                "fact": fact,
                "learned_at": datetime.now().isoformat(),
                "learned_by": user_profile.user_id if user_profile else None
            }
            self._save_knowledge()
            
            return f"✅ Запомнил: '{fact}'. Буду помнить об этом! 🧠"
        
        return "Пожалуйста, укажи, что именно запомнить. Например: 'запомни, что Земля круглая'"
    
    def _recall_info(self, message: str, user_profile: UserProfile = None) -> str:
        """Вспоминание информации"""
        if "learned_facts" in self.knowledge and self.knowledge["learned_facts"]:
            facts = list(self.knowledge["learned_facts"].values())
            random_fact = random.choice(facts)
            return f"📚 Я помню, что: {random_fact['fact']}"
        
        # Ищем в QnA
        for question, answer in self.knowledge["qna"].items():
            if question in message.lower():
                return answer
        
        return "Я еще мало что знаю. Расскажи мне что-нибудь интересное!"
    
    def _clear_memory(self, message: str, user_profile: UserProfile = None) -> str:
        """Очистка памяти"""
        return "Для очистки памяти используй команду /clearmemory"
    
    def _how_i_learn(self, message: str, user_profile: UserProfile = None) -> str:
        """Рассказать о процессе обучения"""
        stats = self.knowledge["statistics"]
        return (f"🧠 *Как я учусь:*\n"
                f"• Автообучение: {'ВКЛ' if self.learning_modes['auto_correction'] else 'ВЫКЛ'}\n"
                f"• Выучено ответов: {stats['learned_qna']}\n"
                f"• Получено исправлений: {stats['corrections_received']}\n"
                f"• Всего сообщений: {stats['total_messages']}\n"
                f"• Всего пользователей: {stats.get('total_users', 0)}\n\n"
                f"Когда я не знаю ответа, я спрашиваю у вас! 💡")
    
    def _weather_handler(self, message: str, user_profile: UserProfile = None) -> str:
        """Обработчик запроса погоды"""
        return "🌤️ Напиши название города для получения погоды, например: 'Москва' или 'погода Москва'"
    
    def _stats_handler(self, message: str, user_profile: UserProfile = None) -> str:
        """Обработчик статистики"""
        stats = self.knowledge["statistics"]
        user_stats = ""
        
        if user_profile:
            user_stats = (f"\n📊 *Твоя статистика:*\n"
                         f"• Сообщений: {user_profile.total_messages}\n"
                         f"• Внесено знаний: {user_profile.learned_contributions}\n"
                         f"• Диалогов: {user_profile.conversation_count}")
        
        return (f"📈 *Глобальная статистика:*\n"
                f"• Всего сообщений: {stats['total_messages']}\n"
                f"• Выучено ответов: {stats['learned_qna']}\n"
                f"• Всего пользователей: {stats.get('total_users', 0)}{user_stats}")
    
    def _currency_handler(self, message: str, user_profile: UserProfile = None) -> str:
        """Обработчик курсов валют"""
        return "💱 Функция курсов валют в разработке. Скоро будет доступно!"
    
    def _news_handler(self, message: str, user_profile: UserProfile = None) -> str:
        """Обработчик новостей"""
        return "📰 Функция новостей в разработке. Скоро будет доступно!"
    
    def _joke_handler(self, message: str, user_profile: UserProfile = None) -> str:
        """Обработчик анекдотов"""
        jokes = [
            "В разработке"
        ]
        return f"😂 {random.choice(jokes)}"
    
    # ==================== МЕТОДЫ ПОГОДЫ ====================
    
    async def get_weather(self, city: str) -> str:
        """Получить погоду для города"""
        # Проверяем кэш
        city_lower = city.lower()
        current_time = datetime.now()
        
        if city_lower in self.weather_cache:
            cache_time, weather_data = self.weather_cache[city_lower]
            if current_time - cache_time < self.cache_duration:
                return weather_data
        
        # Если нет API ключа, возвращаем сообщение
        if not self.weather_config.api_key:
            return "🌤️ Для работы погодного сервиса нужен API ключ OpenWeatherMap.\nДобавьте его в файл weather_config.json"
        
        # Получаем погоду через API
        try:
            url = f"{self.weather_config.base_url}?q={city}&appid={self.weather_config.api_key}&units={self.weather_config.units}&lang={self.weather_config.lang}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        weather = self._format_weather_data(data)
                        # Сохраняем в кэш
                        self.weather_cache[city_lower] = (current_time, weather)
                        return weather
                    elif response.status == 404:
                        return f"🌍 Город '{city}' не найден. Проверьте правильность написания."
                    else:
                        return f"⚠️ Ошибка получения погоды. Код ошибки: {response.status}"
        except Exception as e:
            logger.error(f"Ошибка получения погоды: {e}")
            return f"⚠️ Произошла ошибка при получении погоды: {str(e)}"
    
    def _format_weather_data(self, data: Dict) -> str:
        """Форматирование данных о погоде"""
        city = data.get("name", "Неизвестный город")
        country = data.get("sys", {}).get("country", "")
        temp = data.get("main", {}).get("temp", 0)
        feels_like = data.get("main", {}).get("feels_like", 0)
        humidity = data.get("main", {}).get("humidity", 0)
        pressure = data.get("main", {}).get("pressure", 0)
        weather_desc = data.get("weather", [{}])[0].get("description", "").capitalize()
        wind_speed = data.get("wind", {}).get("speed", 0)
        
        # Иконка погоды
        weather_icon = self._get_weather_icon(weather_desc)
        
        return (f"{weather_icon} *Погода в {city}, {country}*\n\n"
                f"• Температура: {temp:.1f}°C\n"
                f"• Ощущается как: {feels_like:.1f}°C\n"
                f"• {weather_desc}\n"
                f"• Влажность: {humidity}%\n"
                f"• Давление: {pressure} hPa\n"
                f"• Ветер: {wind_speed} м/с")
    
    def _get_weather_icon(self, description: str) -> str:
        """Получить иконку для погоды"""
        description_lower = description.lower()
        
        if "дождь" in description_lower:
            return "🌧️"
        elif "снег" in description_lower:
            return "❄️"
        elif "облачно" in description_lower:
            return "☁️"
        elif "ясно" in description_lower or "солнце" in description_lower:
            return "☀️"
        elif "туман" in description_lower or "тумано" in description_lower:
            return "🌫️"
        elif "гроза" in description_lower:
            return "⛈️"
        else:
            return "🌤️"
    
    # ==================== МЕТОДЫ ОБУЧЕНИЯ ====================
    
    def _check_qna_match(self, user_message: str) -> Optional[str]:
        """Проверяет, есть ли ответ в базе QnA"""
        user_msg_lower = user_message.lower()
        
        # Прямое совпадение
        if user_msg_lower in self.knowledge.get("qna", {}):
            return self.knowledge["qna"][user_msg_lower]
        
        # Частичное совпадение
        for question, answer in self.knowledge.get("qna", {}).items():
            if question in user_msg_lower or user_msg_lower in question:
                return answer
        
        # Ключевые слова
        keywords = self._extract_keywords(user_msg_lower)
        for question, answer in self.knowledge.get("qna", {}).items():
            question_keywords = self._extract_keywords(question)
            common = set(keywords) & set(question_keywords)
            if len(common) >= 2:
                return answer
        
        return None
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Извлекает ключевые слова из текста"""
        stop_words = {'что', 'как', 'кто', 'где', 'когда', 'почему', 'зачем', 
                     'это', 'этот', 'эта', 'эти', 'тот', 'та', 'те', 'свой',
                     'мои', 'твои', 'его', 'её', 'их', 'наш', 'ваш', 'весь',
                     'все', 'всё', 'какой', 'какая', 'какие', 'такой', 'такая'}
        
        words = re.findall(r'\b\w+\b', text.lower())
        return [w for w in words if w not in stop_words and len(w) > 2]
    
    def _calculate_confidence(self, user_message: str) -> float:
        """Рассчитывает уверенность в ответе"""
        if user_message.lower() in self.knowledge.get("qna", {}):
            return 0.9
        
        keywords = self._extract_keywords(user_message)
        if not keywords:
            return 0.0
        
        best_match = 0.0
        for question in self.knowledge.get("qna", {}).keys():
            question_keywords = self._extract_keywords(question)
            if not question_keywords:
                continue
            
            common = set(keywords) & set(question_keywords)
            similarity = len(common) / max(len(keywords), len(question_keywords))
            best_match = max(best_match, similarity)
        
        return best_match
    
    async def process_message(self, user_id: int, user_message: str, 
                             username: str = None, first_name: str = None, 
                             last_name: str = None, is_correction: bool = False, 
                             correction_data: Dict = None) -> Dict[str, Any]:
        """Основной метод обработки сообщения"""
        # Получаем профиль пользователя
        user_profile = self.get_or_create_user_profile(
            user_id, username, first_name, last_name
        )
        
        # Обновляем статистику
        self.update_user_stats(user_id, "total_messages")
        
        # Если это исправление
        if is_correction and correction_data:
            question = correction_data.get("question")
            answer = user_message
            
            if question:
                # Сохраняем в базу знаний
                if "qna" not in self.knowledge:
                    self.knowledge["qna"] = {}
                
                self.knowledge["qna"][question.lower()] = answer
                self.update_user_stats(user_id, "learned_contributions")
                self.knowledge["statistics"]["learned_qna"] += 1
                self.knowledge["statistics"]["corrections_received"] += 1
                self._save_knowledge()
                
                return {
                    "response": f"✅ Отлично! Запомнил: на вопрос '{question}' нужно отвечать: '{answer}'",
                    "needs_followup": False,
                    "action": None
                }
        
        # Проверяем правила
        for pattern, handler in self.rules.items():
            if re.search(pattern, user_message.lower()):
                response = handler(user_message, user_profile)
                self._learn_from_interaction(user_message, response, user_id)
                return {
                    "response": response,
                    "needs_followup": False,
                    "action": None
                }
        
        # Проверяем базу знаний
        qna_answer = self._check_qna_match(user_message)
        if qna_answer:
            self._learn_from_interaction(user_message, qna_answer, user_id)
            return {
                "response": qna_answer,
                "needs_followup": False,
                "action": None
            }
        
        # Проверяем, не запрос ли это погоды
        if any(word in user_message.lower() for word in ["погода", "weather", "прогноз"]):
            # Извлекаем город из сообщения
            city_match = re.search(r'погода\s+(.+)', user_message.lower())
            if city_match:
                city = city_match.group(1).strip()
                weather = await self.get_weather(city)
                return {
                    "response": weather,
                    "needs_followup": False,
                    "action": None
                }
            else:
                return {
                    "response": "🌤️ Напиши название города для получения погоды",
                    "needs_followup": True,
                    "action": "weather"
                }
        
        # Если не знаем ответа и включено автообучение
        confidence = self._calculate_confidence(user_message)
        if confidence < self.learning_modes['confidence_threshold'] and self.learning_modes['auto_correction']:
            return {
                "response": f"🤔 Я не уверен в ответе на вопрос: '{user_message}'. Можешь подсказать правильный ответ?",
                "needs_followup": True,
                "action": "correction",
                "correction_data": {"question": user_message}
            }
        
        # Запасные ответы
        return {
            "response": self._get_fallback_response(user_message),
            "needs_followup": False,
            "action": None
        }
    
    def _learn_from_interaction(self, question: str, answer: str, user_id: int):
        """Учимся на успешном взаимодействии"""
        keywords = self._extract_keywords(question.lower())
        if len(keywords) >= 2:
            key = " ".join(sorted(keywords)[:2])
            
            if "interaction_stats" not in self.knowledge:
                self.knowledge["interaction_stats"] = {}
            
            if key not in self.knowledge["interaction_stats"]:
                self.knowledge["interaction_stats"][key] = {}
            
            if answer not in self.knowledge["interaction_stats"][key]:
                self.knowledge["interaction_stats"][key][answer] = 0
            
            self.knowledge["interaction_stats"][key][answer] += 1
    
    def _get_fallback_response(self, user_message: str) -> str:
        """Запасной ответ"""
        fallback_responses = [
            f"Извини, я не совсем понял вопрос: '{user_message}'. Можешь переформулировать?",
            f"Интересно... '{user_message}'. Давай поговорим о чем-нибудь другом?",
            f"Пока я не готов ответить на этот вопрос. Спроси что-нибудь другое!",
            f"Хм, мне нужно подумать над этим. А пока могу ответить на другие вопросы!",
            f"Я еще учусь! Спроси меня о чем-то другом, например о погоде или времени."
        ]
        
        return random.choice(fallback_responses)

# ==================== TELEGRAM BOT ====================

class NixAITelegramBot:
    """Telegram бот для Nix AI"""
    
    def __init__(self, token: str):
        self.token = token
        self.ai = NixAICore()
        
        # Инициализация бота
        self.bot = Bot(token=token)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        
        # Регистрация обработчиков
        self._register_handlers()
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        # Команды
        self.dp.message.register(self.start_command, CommandStart())
        self.dp.message.register(self.help_command, Command("help"))
        self.dp.message.register(self.weather_command, Command("weather"))
        self.dp.message.register(self.stats_command, Command("stats"))
        self.dp.message.register(self.knowledge_command, Command("knowledge"))
        self.dp.message.register(self.clear_memory_command, Command("clearmemory"))
        self.dp.message.register(self.settings_command, Command("settings"))
        
        # Обработчики состояний
        self.dp.message.register(self.handle_weather_city, DialogStates.AWAITING_WEATHER_CITY)
        self.dp.message.register(self.handle_correction, DialogStates.AWAITING_CORRECTION)
        self.dp.message.register(self.handle_remember, DialogStates.AWAITING_REMEMBER)
        
        # Обработчик всех сообщений
        self.dp.message.register(self.handle_message)
        
        # Обработчик callback запросов
        self.dp.callback_query.register(self.handle_callback)
    
    # ==================== КОМАНДЫ ====================
    
    async def start_command(self, message: Message):
        """Обработчик команды /start"""
        keyboard = self._get_main_keyboard()
        
        welcome_text = (
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"🤖 Я *Nix AI* - автообучающийся ИИ помощник.\n"
            f"Я учусь на каждом нашем диалоге и могу:\n\n"
            f"• Отвечать на вопросы\n"
            f"• Рассказывать о погоде 🌤️\n"
            f"• Показывать время и дату\n"
            f"• Запоминать информацию\n"
            f"• И многое другое!\n\n"
            f"Просто начни общаться со мной!"
        )
        
        await message.answer(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    async def help_command(self, message: Message):
        """Обработчик команды /help"""
        help_text = self.ai._help("", None)
        await message.answer(help_text, parse_mode="Markdown")
    
    async def weather_command(self, message: Message, state: FSMContext):
        """Обработчик команды /weather"""
        await message.answer("🌤️ Напиши название города:")
        await state.set_state(DialogStates.AWAITING_WEATHER_CITY)
    
    async def stats_command(self, message: Message):
        """Обработчик команды /stats"""
        result = await self.ai.process_message(
            message.from_user.id,
            "статистика",
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name
        )
        await message.answer(result["response"], parse_mode="Markdown")
    
    async def knowledge_command(self, message: Message):
        """Обработчик команды /knowledge"""
        qna = self.ai.knowledge.get("qna", {})
        
        if not qna:
            await message.answer("Я еще ничего не выучил. Задай вопрос, и я научусь!")
            return
        
        total = len(qna)
        response = f"📚 Я знаю ответы на *{total} вопросов*:\n\n"
        
        # Показываем 5 случайных вопросов
        if total <= 5:
            sample_items = list(qna.items())
        else:
            sample_items = random.sample(list(qna.items()), 5)
        
        for i, (question, answer) in enumerate(sample_items, 1):
            response += f"*{i}. Вопрос:* {question}\n"
            response += f"*Ответ:* {answer}\n\n"
        
        if total > 5:
            response += f"... и еще *{total - 5}* вопросов!"
        
        await message.answer(response, parse_mode="Markdown")
    
    async def clear_memory_command(self, message: Message):
        """Обработчик команды /clearmemory"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, очистить", callback_data="clear_yes")],
            [InlineKeyboardButton(text="❌ Нет, оставить", callback_data="clear_no")]
        ])
        
        await message.answer(
            "⚠️ *ВНИМАНИЕ!*\n\n"
            "Это удалит ВСЕ выученные мной знания.\n"
            "Вы уверены, что хотите очистить память?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    async def settings_command(self, message: Message):
        """Обработчик команды /settings"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Автообучение", callback_data="toggle_learning")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats_detailed")],
            [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_chat")],
        ])
        
        learning_status = "ВКЛ" if self.ai.learning_modes['auto_correction'] else "ВЫКЛ"
        
        await message.answer(
            f"⚙️ *Настройки Nix AI*\n\n"
            f"• Автообучение: *{learning_status}*\n"
            f"• Порог уверенности: *{self.ai.learning_modes['confidence_threshold']}*\n"
            f"• Спрашивать перед обучением: *{'НЕТ' if self.ai.learning_modes['ask_before_learning'] else 'ДА'}*\n\n"
            f"Изменить настройки:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ ====================
    
    async def handle_weather_city(self, message: Message, state: FSMContext):
        """Обработка ввода города для погоды"""
        city = message.text.strip()
        if not city:
            await message.answer("Пожалуйста, введите название города.")
            return
        
        await message.answer(f"🌤️ Получаю погоду для *{city}*...", parse_mode="Markdown")
        
        weather = await self.ai.get_weather(city)
        await message.answer(weather, parse_mode="Markdown")
        
        await state.clear()
    
    async def handle_correction(self, message: Message, state: FSMContext):
        """Обработка исправления от пользователя"""
        user_data = await state.get_data()
        correction_data = user_data.get("correction_data", {})
        
        result = await self.ai.process_message(
            message.from_user.id,
            message.text,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            is_correction=True,
            correction_data=correction_data
        )
        
        await message.answer(result["response"])
        await state.clear()
    
    async def handle_remember(self, message: Message, state: FSMContext):
        """Обработка запоминания информации"""
        result = await self.ai.process_message(
            message.from_user.id,
            f"запомни {message.text}",
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name
        )
        
        await message.answer(result["response"])
        await state.clear()
    
    # ==================== ОСНОВНОЙ ОБРАБОТЧИК ====================
    
    async def handle_message(self, message: Message, state: FSMContext):
        """Обработка всех сообщений"""
        # Пропускаем команды
        if message.text and message.text.startswith('/'):
            return
        
        user_id = message.from_user.id
        user_message = message.text
        
        if not user_message:
            await message.answer("Пожалуйста, отправьте текстовое сообщение.")
            return
        
        # Получаем текущее состояние
        current_state = await state.get_state()
        
        # Если ожидаем ввод города для погоды
        if current_state == DialogStates.AWAITING_WEATHER_CITY:
            await self.handle_weather_city(message, state)
            return
        
        # Если ожидаем исправление
        if current_state == DialogStates.AWAITING_CORRECTION:
            await self.handle_correction(message, state)
            return
        
        # Если ожидаем информацию для запоминания
        if current_state == DialogStates.AWAITING_REMEMBER:
            await self.handle_remember(message, state)
            return
        
        # Обрабатываем сообщение
        result = await self.ai.process_message(
            user_id,
            user_message,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name
        )
        
        # Отправляем ответ
        await message.answer(result["response"], parse_mode="Markdown")
        
        # Если нужен follow-up
        if result["needs_followup"]:
            if result["action"] == "correction":
                await state.set_data({"correction_data": result.get("correction_data", {})})
                await state.set_state(DialogStates.AWAITING_CORRECTION)
            elif result["action"] == "weather":
                await state.set_state(DialogStates.AWAITING_WEATHER_CITY)
    
    # ==================== CALLBACK ОБРАБОТЧИК ====================
    
    async def handle_callback(self, callback_query: CallbackQuery, state: FSMContext):
        """Обработка callback запросов"""
        data = callback_query.data
        await callback_query.answer()
        
        if data == "clear_yes":
            self.ai.knowledge["qna"] = {}
            self.ai.knowledge["learned_facts"] = {}
            self.ai.knowledge["interaction_stats"] = {}
            self.ai._save_knowledge()
            
            await callback_query.message.edit_text(
                "✅ Память очищена. Я все забыл. 🧹\n\n"
                "Теперь я снова как чистый лист!"
            )
            
        elif data == "clear_no":
            await callback_query.message.edit_text(
                "❌ Очистка памяти отменена.\n\n"
                "Все знания сохранены."
            )
        
        elif data == "toggle_learning":
            self.ai.learning_modes['auto_correction'] = not self.ai.learning_modes['auto_correction']
            status = "ВКЛ" if self.ai.learning_modes['auto_correction'] else "ВЫКЛ"
            
            await callback_query.message.edit_text(
                f"✅ Автообучение теперь *{status}*",
                parse_mode="Markdown"
            )
        
        elif data == "stats_detailed":
            stats = self.ai.knowledge["statistics"]
            response = (
                f"📊 *Детальная статистика:*\n\n"
                f"• Всего сообщений: *{stats['total_messages']}*\n"
                f"• Выучено ответов: *{stats['learned_qna']}*\n"
                f"• Исправлений получено: *{stats['corrections_received']}*\n"
                f"• Всего пользователей: *{stats.get('total_users', 0)}*\n"
                f"• Первый запуск: *{stats.get('first_start', 'неизвестно')}*\n"
            )
            await callback_query.message.answer(response, parse_mode="Markdown")
        
        elif data == "reset_chat":
            await state.clear()
            await callback_query.message.answer("✅ Диалог сброшен. Начнем общение заново!")
        
        elif data == "weather":
            await callback_query.message.answer("🌤️ Напиши название города:")
            await state.set_state(DialogStates.AWAITING_WEATHER_CITY)
    
    # ==================== УТИЛИТЫ ====================
    
    def _get_main_keyboard(self) -> ReplyKeyboardMarkup:
        """Создание основной клавиатуры"""
        keyboard = [
            [KeyboardButton(text="🌤️ Погода"), KeyboardButton(text="🕐 Время")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="❓ Помощь")],
            [KeyboardButton(text="🎯 Что ты умеешь?"), KeyboardButton(text="😂 Анекдот")],
        ]
        return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    
    async def run(self):
        """Запуск бота"""
        logger.info("🤖 Nix AI Telegram Bot запущен!")
        await self.dp.start_polling(self.bot)

# ==================== КОНФИГУРАЦИЯ ====================

def load_config() -> Dict:
    """Загрузка конфигурации"""
    config_file = "bot_config.json"
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
    
    # Создаем шаблон конфигурации
    default_config = {
        "telegram_token": "ВАШ_TELEGRAM_BOT_TOKEN",
        "openweather_api_key": "ВАШ_OPENWEATHER_API_KEY"
    }
    
    # Сохраняем шаблон
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(default_config, f, ensure_ascii=False, indent=2)
    
    logger.warning(f"Создан файл конфигурации {config_file}. Заполните его!")
    return default_config

def create_weather_config():
    """Создание конфигурации погоды"""
    config_file = "weather_config.json"
    
    if not os.path.exists(config_file):
        default_config = {
            "api_key": "",
            "base_url": "http://api.openweathermap.org/data/2.5/weather",
            "units": "metric",
            "lang": "ru"
        }
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Создан файл конфигурации погоды: {config_file}")

# ==================== ЗАПУСК ====================

async def main():
    """Основная функция"""
    logger.info("🚀 Запуск Nix AI Telegram Bot...")
    
    # Загружаем конфигурацию
    config = load_config()
    create_weather_config()
    
    token = config.get("telegram_token")
    
    if not token or token == "ВАШ_TELEGRAM_BOT_TOKEN":
        logger.error("❌ Пожалуйста, установите Telegram Bot Token в файле bot_config.json")
        logger.info("1. Создайте бота через @BotFather")
        logger.info("2. Получите токен")
        logger.info("3. Вставьте токен в bot_config.json")
        return
    
    # Создаем и запускаем бота
    bot = NixAITelegramBot(token)
    
    # Если есть API ключ для погоды, сохраняем его
    weather_api_key = config.get("openweather_api_key")
    if weather_api_key and weather_api_key != "ВАШ_OPENWEATHER_API_KEY":
        bot.ai.weather_config.api_key = weather_api_key
        logger.info("✅ API ключ OpenWeatherMap загружен")
    else:
        logger.warning("⚠️ API ключ OpenWeatherMap не настроен. Функция погоды будет ограничена.")
    
    # Запускаем бота
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
