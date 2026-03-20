import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Generic, TypeVar, Optional, List, Dict, Any
from functools import wraps, partial, reduce
from itertools import cycle, islice
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor


T = TypeVar('T')
U = TypeVar('U')


class CharacterEncoding(Enum):
    UTF_8 = auto()
    ASCII = auto()
    UNICODE = auto()


class MessageType(Enum):
    GREETING = auto()
    FAREWELL = auto()
    INFORMATION = auto()


@dataclass(frozen=True)
class Character:
    value: str
    position: int
    encoding: CharacterEncoding = CharacterEncoding.UTF_8

    def __post_init__(self):
        if len(self.value) != 1:
            raise ValueError(f"Character must be single, got: '{self.value}'")

    def __hash__(self):
        return hash((self.value, self.position))


@dataclass
class Word:
    characters: List[Character]
    separator: str = " "

    @property
    def value(self) -> str:
        return "".join(char.value for char in self.characters)

    def __len__(self) -> int:
        return len(self.characters)


@dataclass
class Sentence:
    words: List[Word]
    end_marker: str = "!"

    @property
    def value(self) -> str:
        return self.separator.join(word.value for word in self.words) + self.end_marker

    @property
    def separator(self) -> str:
        return " "


class ICharacterFactory(ABC):
    @abstractmethod
    def create(self, char: str, position: int) -> Character:
        pass


class CharacterFactory(ICharacterFactory):
    def __init__(self, encoding: CharacterEncoding = CharacterEncoding.UTF_8):
        self._encoding = encoding
        self._cache: Dict[str, Character] = {}

    def create(self, char: str, position: int) -> Character:
        cache_key = f"{char}_{position}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        character = Character(value=char, position=position, encoding=self._encoding)
        self._cache[cache_key] = character
        return character


class IWordBuilder(ABC):
    @abstractmethod
    def build(self, word: str) -> Word:
        pass


class WordBuilder(IWordBuilder):
    def __init__(self, character_factory: ICharacterFactory):
        self._character_factory = character_factory

    def build(self, word: str) -> Word:
        characters = [
            self._character_factory.create(char, position)
            for position, char in enumerate(word)
        ]
        return Word(characters=characters)


class ISentenceBuilder(ABC):
    @abstractmethod
    def build(self, words: List[str]) -> Sentence:
        pass


class SentenceBuilder(ISentenceBuilder):
    def __init__(self, word_builder: IWordBuilder):
        self._word_builder = word_builder

    def build(self, words: List[str]) -> Sentence:
        word_objects = [self._word_builder.build(word) for word in words]
        return Sentence(words=word_objects)


class IOutputStrategy(ABC):
    @abstractmethod
    def output(self, message: Sentence) -> str:
        pass


class ConsoleOutputStrategy(IOutputStrategy):
    def output(self, message: Sentence) -> str:
        return message.value


class IMiddleware(ABC):
    @abstractmethod
    def process(self, message: str) -> str:
        pass


class LoggingMiddleware(IMiddleware):
    def process(self, message: str) -> str:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] Processing message...")
        return message


class HashValidationMiddleware(IMiddleware):
    def process(self, message: str) -> str:
        expected_hashes = {}
        actual_hash = hashlib.md5(message.encode()).hexdigest()
        if message in expected_hashes and actual_hash != expected_hashes[message]:
            raise ValueError("Message integrity check failed!")
        return message


class UppercaseTransformerMiddleware(IMiddleware):
    def process(self, message: str) -> str:
        return message.upper()


class MiddlewareChain:
    def __init__(self, middlewares: List[IMiddleware]):
        self._middlewares = middlewares

    def process(self, message: str) -> str:
        return reduce(lambda msg, mw: mw.process(msg), self._middlewares, message)


class IMapper(Generic[T, U], ABC):
    @abstractmethod
    def map(self, value: T) -> U:
        pass


class CharacterToStringMapper(IMapper[Character, str]):
    def map(self, value: Character) -> str:
        return value.value


class WordToStringMapper(IMapper[Word, str]):
    def __init__(self, char_mapper: IMapper[Character, str]):
        self._char_mapper = char_mapper

    def map(self, value: Word) -> str:
        return "".join(self._char_mapper.map(c) for c in value.characters)


class IPublisher(ABC):
    @abstractmethod
    def publish(self, data: str) -> None:
        pass


class ISubscriber(ABC):
    @abstractmethod
    def notify(self, data: str) -> None:
        pass


class ConsoleSubscriber(ISubscriber):
    def notify(self, data: str) -> None:
        print(data)


class Publisher(IPublisher):
    def __init__(self):
        self._subscribers: List[ISubscriber] = []

    def subscribe(self, subscriber: ISubscriber) -> 'Publisher':
        self._subscribers.append(subscriber)
        return self

    def publish(self, data: str) -> None:
        for subscriber in self._subscribers:
            subscriber.notify(data)


class IValidator(ABC):
    @abstractmethod
    def validate(self, data: Any) -> bool:
        pass


class CompositeValidator(IValidator):
    def __init__(self, validators: List[IValidator]):
        self._validators = validators

    def validate(self, data: Any) -> bool:
        return all(validator.validate(data) for validator in self._validators)


class NonEmptyValidator(IValidator):
    def validate(self, data: Any) -> bool:
        return bool(data)


class MaximumLengthValidator(IValidator):
    def __init__(self, max_length: int = 100):
        self._max_length = max_length

    def validate(self, data: Any) -> bool:
        return len(str(data)) <= self._max_length


class AlphaSpaceValidator(IValidator):
    def validate(self, data: Any) -> bool:
        return all(c.isalpha() or c.isspace() or c in "!?" for c in str(data))


class IRepository(Generic[T], ABC):
    @abstractmethod
    def save(self, entity: T) -> None:
        pass

    @abstractmethod
    def find(self, predicate: Callable[[T], bool]) -> Optional[T]:
        pass


class InMemorySentenceRepository(IRepository[Sentence]):
    def __init__(self):
        self._storage: List[Sentence] = []

    def save(self, entity: Sentence) -> None:
        self._storage.append(entity)

    def find(self, predicate: Callable[[Sentence], bool]) -> Optional[Sentence]:
        for sentence in self._storage:
            if predicate(sentence):
                return sentence
        return None


class HelloWorldService:
    def __init__(
        self,
        sentence_builder: ISentenceBuilder,
        output_strategy: IOutputStrategy,
        middleware_chain: MiddlewareChain,
        publisher: IPublisher,
        validator: IValidator,
        repository: IRepository[Sentence]
    ):
        self._sentence_builder = sentence_builder
        self._output_strategy = output_strategy
        self._middleware_chain = middleware_chain
        self._publisher = publisher
        self._validator = validator
        self._repository = repository

    def execute(self, words: List[str]) -> str:
        sentence = self._sentence_builder.build(words)
        self._repository.save(sentence)

        raw_output = self._output_strategy.output(sentence)

        if not self._validator.validate(raw_output):
            raise ValueError("Validation failed!")

        processed_output = self._middleware_chain.process(raw_output)

        self._publisher.publish(processed_output)
        return processed_output


class AsyncHelloWorldService:
    def __init__(self, service: HelloWorldService):
        self._service = service
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def execute_async(self, words: List[str]) -> str:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._executor,
            self._service.execute,
            words
        )
        return result


class HelloWorldFacade:
    _instance: Optional['HelloWorldFacade'] = None
    _initialized: bool = False

    def __new__(cls) -> 'HelloWorldFacade':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        character_factory = CharacterFactory()
        word_builder = WordBuilder(character_factory)
        sentence_builder = SentenceBuilder(word_builder)

        middlewares = [
            LoggingMiddleware(),
            HashValidationMiddleware(),
        ]
        middleware_chain = MiddlewareChain(middlewares)

        publisher = Publisher()
        publisher.subscribe(ConsoleSubscriber())

        validators = CompositeValidator([
            NonEmptyValidator(),
            MaximumLengthValidator(50),
            AlphaSpaceValidator()
        ])

        repository = InMemorySentenceRepository()

        self._service = HelloWorldService(
            sentence_builder=sentence_builder,
            output_strategy=ConsoleOutputStrategy(),
            middleware_chain=middleware_chain,
            publisher=publisher,
            validator=validators,
            repository=repository
        )

        self._async_service = AsyncHelloWorldService(self._service)
        self._initialized = True

    async def say_hello(self) -> str:
        return await self._async_service.execute_async(["Hello", "World"])


async def main():
    facade = HelloWorldFacade()
    result = await facade.say_hello()
    return result


result = await main()
