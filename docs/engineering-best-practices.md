# Software Engineering Best Practices & Design Guidelines

This document contains comprehensive engineering guidelines for building production-quality software. Use these principles when designing and implementing any project.

---

## Table of Contents
1. [Project Architecture Principles](#project-architecture-principles)
2. [Web Application Design](#web-application-design)
3. [Frontend Development Guidelines](#frontend-development-guidelines)
4. [Backend Development Guidelines](#backend-development-guidelines)
5. [API Design](#api-design)
6. [Database Design](#database-design)
7. [Testing Strategy](#testing-strategy)
8. [Security Best Practices](#security-best-practices)
9. [Performance Optimization](#performance-optimization)
10. [Deployment & DevOps](#deployment--devops)

---

## Project Architecture Principles

### SOLID Principles
- **Single Responsibility**: Each module/class should have one reason to change
- **Open/Closed**: Open for extension, closed for modification
- **Liskov Substitution**: Subtypes must be substitutable for their base types
- **Interface Segregation**: Many specific interfaces are better than one general interface
- **Dependency Inversion**: Depend on abstractions, not concretions

### Clean Architecture Layers
1. **Entities**: Core business logic, independent of frameworks
2. **Use Cases**: Application-specific business rules
3. **Interface Adapters**: Convert data between use cases and external formats
4. **Frameworks & Drivers**: External tools (databases, web frameworks, UI)

### Design Patterns to Apply
- **Repository Pattern**: Abstract data access layer
- **Factory Pattern**: Object creation without specifying exact class
- **Strategy Pattern**: Define family of algorithms, make them interchangeable
- **Observer Pattern**: One-to-many dependency between objects
- **Adapter Pattern**: Convert interface of a class into another interface
- **Decorator Pattern**: Attach additional responsibilities dynamically

---

## Web Application Design

### Project Structure (Next.js / React)
```
project/
├── app/                    # Next.js app router pages
│   ├── (auth)/            # Route groups for authentication
│   ├── (dashboard)/       # Protected dashboard routes
│   ├── api/               # API routes
│   ├── layout.tsx         # Root layout with providers
│   ├── page.tsx           # Home page
│   └── globals.css        # Global styles
├── components/
│   ├── ui/                # Reusable UI primitives (Button, Input, Card)
│   ├── forms/             # Form components
│   ├── layouts/           # Layout components (Header, Footer, Sidebar)
│   └── features/          # Feature-specific components
├── lib/
│   ├── api/               # API client functions
│   ├── hooks/             # Custom React hooks
│   ├── utils/             # Utility functions
│   └── validations/       # Zod schemas / validation logic
├── types/                 # TypeScript type definitions
├── constants/             # App constants and config
└── public/                # Static assets
```

### Landing Page Requirements
Every landing page MUST include:
1. **Hero Section**: Clear value proposition, CTA button, hero image/illustration
2. **Features Section**: 3-6 key features with icons and descriptions
3. **Social Proof**: Testimonials, logos, stats, or case studies
4. **Pricing Section**: Clear pricing tiers (if applicable)
5. **FAQ Section**: Common questions and answers
6. **Footer**: Navigation, legal links, social media, newsletter signup

### UI/UX Requirements
- **Mobile-first responsive design** with breakpoints: sm(640px), md(768px), lg(1024px), xl(1280px)
- **Dark mode support** using CSS variables or Tailwind dark: prefix
- **Loading states** for all async operations (skeleton loaders, spinners)
- **Error states** with clear messaging and recovery actions
- **Empty states** with helpful guidance
- **Micro-interactions** and smooth transitions (150-300ms)
- **Consistent spacing** using a spacing scale (4px base)
- **Accessible color contrast** (WCAG AA minimum: 4.5:1 for text)

---

## Frontend Development Guidelines

### TypeScript Best Practices
```typescript
// Always define explicit types for props
interface ButtonProps {
  variant: 'primary' | 'secondary' | 'ghost';
  size: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}

// Use const assertions for constants
const ROUTES = {
  HOME: '/',
  DASHBOARD: '/dashboard',
  SETTINGS: '/settings',
} as const;

// Use discriminated unions for state
type AsyncState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: Error };

// Use generic components for reusability
interface ListProps<T> {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  keyExtractor: (item: T) => string;
}
```

### React Component Patterns
```tsx
// Compound Components Pattern
<Card>
  <Card.Header>Title</Card.Header>
  <Card.Body>Content</Card.Body>
  <Card.Footer>Actions</Card.Footer>
</Card>

// Render Props Pattern
<DataFetcher url="/api/users">
  {({ data, loading, error }) => (
    loading ? <Spinner /> : <UserList users={data} />
  )}
</DataFetcher>

// Custom Hook Pattern
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);
  
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  
  return debouncedValue;
}
```

### State Management Guidelines
- **Local state**: useState for component-specific UI state
- **Shared state**: Context API for theme, auth, simple global state
- **Server state**: React Query / SWR for API data (caching, revalidation)
- **Complex state**: Zustand or Redux Toolkit for complex client state

### Form Handling
- Use **React Hook Form** for form state management
- Use **Zod** for schema validation
- Always include:
  - Client-side validation with real-time feedback
  - Server-side validation
  - Accessible error messages (aria-describedby)
  - Loading state on submit button
  - Disable submit during submission

---

## Backend Development Guidelines

### API Structure (Python/FastAPI)
```python
project/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── users.py
│   │   │   │   ├── products.py
│   │   │   │   └── orders.py
│   │   │   └── router.py
│   │   └── deps.py          # Dependency injection
│   ├── core/
│   │   ├── config.py        # Settings/configuration
│   │   ├── security.py      # Auth utilities
│   │   └── exceptions.py    # Custom exceptions
│   ├── models/              # SQLAlchemy/Pydantic models
│   ├── schemas/             # Request/Response schemas
│   ├── services/            # Business logic layer
│   ├── repositories/        # Data access layer
│   └── main.py
├── tests/
├── alembic/                 # Database migrations
└── docker-compose.yml
```

### Service Layer Pattern
```python
# services/user_service.py
class UserService:
    def __init__(self, user_repo: UserRepository, email_service: EmailService):
        self.user_repo = user_repo
        self.email_service = email_service
    
    async def create_user(self, user_data: UserCreate) -> User:
        # Validate business rules
        if await self.user_repo.exists_by_email(user_data.email):
            raise UserAlreadyExistsError(user_data.email)
        
        # Create user
        user = await self.user_repo.create(user_data)
        
        # Side effects
        await self.email_service.send_welcome_email(user)
        
        return user
```

### Error Handling
```python
# Always use custom exception classes
class AppException(Exception):
    def __init__(self, message: str, code: str, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code

class NotFoundError(AppException):
    def __init__(self, resource: str, id: str):
        super().__init__(
            message=f"{resource} with id {id} not found",
            code="RESOURCE_NOT_FOUND",
            status_code=404
        )

# Global exception handler
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}}
    )
```

---

## API Design

### RESTful API Conventions
- Use nouns for resources: `/users`, `/products`, `/orders`
- Use HTTP methods correctly:
  - GET: Read (idempotent)
  - POST: Create
  - PUT: Full update (idempotent)
  - PATCH: Partial update
  - DELETE: Remove (idempotent)
- Use proper status codes:
  - 200: Success
  - 201: Created
  - 204: No Content (successful deletion)
  - 400: Bad Request (validation error)
  - 401: Unauthorized
  - 403: Forbidden
  - 404: Not Found
  - 409: Conflict
  - 422: Unprocessable Entity
  - 500: Internal Server Error

### Response Format
```json
// Success response
{
  "data": { ... },
  "meta": {
    "pagination": {
      "page": 1,
      "perPage": 20,
      "total": 100,
      "totalPages": 5
    }
  }
}

// Error response
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input data",
    "details": [
      { "field": "email", "message": "Invalid email format" }
    ]
  }
}
```

### API Versioning
- Use URL path versioning: `/api/v1/users`
- Maintain backward compatibility within a version
- Deprecate with headers: `Deprecation: true`, `Sunset: date`

---

## Database Design

### Schema Design Principles
- Use UUIDs for public-facing IDs (security, no enumeration)
- Use auto-increment integers for internal FKs (performance)
- Always include: `created_at`, `updated_at` timestamps
- Soft delete with `deleted_at` for recoverable data
- Use appropriate indexes for query patterns

### Common Patterns
```sql
-- Base table pattern
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- Audit trail pattern
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,
    user_id UUID REFERENCES users(id),
    changes JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Testing Strategy

### Testing Pyramid
1. **Unit Tests** (70%): Test individual functions/methods in isolation
2. **Integration Tests** (20%): Test component interactions
3. **E2E Tests** (10%): Test complete user flows

### Frontend Testing
```typescript
// Component testing with React Testing Library
describe('Button', () => {
  it('renders with correct text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole('button', { name: /click me/i })).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const onClick = jest.fn();
    render(<Button onClick={onClick}>Click me</Button>);
    await userEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('is disabled when loading', () => {
    render(<Button isLoading>Click me</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
  });
});
```

### Backend Testing
```python
# pytest with fixtures
@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict:
    response = await client.post("/auth/login", json={
        "email": test_user.email,
        "password": "testpassword"
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

async def test_create_user(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": "new@example.com", "name": "New User"}
    )
    assert response.status_code == 201
    assert response.json()["data"]["email"] == "new@example.com"
```

---

## Security Best Practices

### Authentication & Authorization
- Use **JWT** with short expiry (15min) + refresh tokens (7 days)
- Store refresh tokens in httpOnly cookies (not localStorage)
- Implement **RBAC** (Role-Based Access Control) or **ABAC** (Attribute-Based)
- Rate limit authentication endpoints
- Lock accounts after N failed attempts

### Input Validation
- Validate all inputs on both client and server
- Use parameterized queries (never string concatenation)
- Sanitize HTML output to prevent XSS
- Validate file uploads (type, size, content)

### Headers & CORS
```python
# Security headers
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["example.com", "*.example.com"]
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

---

## Performance Optimization

### Frontend Performance
- **Code splitting**: Dynamic imports for routes and heavy components
- **Image optimization**: Next.js Image component, WebP format, lazy loading
- **Bundle analysis**: Keep initial JS under 200KB
- **Caching**: Service workers, browser caching headers
- **Critical CSS**: Inline above-the-fold styles

### Backend Performance
- **Database**: Indexes, query optimization, connection pooling
- **Caching**: Redis for frequently accessed data
- **Async processing**: Background jobs for heavy operations
- **Pagination**: Always paginate list endpoints
- **Compression**: Gzip/Brotli for responses

### Monitoring
- **APM**: Application performance monitoring (response times, errors)
- **Logging**: Structured logging with correlation IDs
- **Metrics**: Request rate, error rate, latency percentiles
- **Alerting**: Set up alerts for anomalies

---

## Deployment & DevOps

### Container Best Practices
```dockerfile
# Multi-stage build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

### CI/CD Pipeline Stages
1. **Lint**: ESLint, Prettier, type checking
2. **Test**: Unit tests, integration tests
3. **Build**: Create production artifacts
4. **Security Scan**: Dependency vulnerabilities, SAST
5. **Deploy to Staging**: Automated deployment
6. **E2E Tests**: Against staging environment
7. **Deploy to Production**: Blue-green or canary deployment

### Environment Management
- Use `.env.example` as template (never commit real secrets)
- Store secrets in: Kubernetes Secrets, AWS Secrets Manager, HashiCorp Vault
- Use different configs per environment (dev, staging, prod)
- Feature flags for gradual rollouts

---

## Code Quality Checklist

Before any code is considered complete, verify:

### Structure
- [ ] Follows established project structure
- [ ] Proper separation of concerns
- [ ] No circular dependencies
- [ ] Reasonable file/function sizes (< 300 lines)

### Quality
- [ ] TypeScript strict mode passing
- [ ] No eslint warnings
- [ ] Unit tests for business logic
- [ ] Error handling for all async operations
- [ ] Loading and error states in UI
- [ ] Accessibility (keyboard navigation, screen readers)

### Security
- [ ] Input validation on all user inputs
- [ ] No secrets in code
- [ ] Authentication/authorization checks
- [ ] CSRF protection for forms

### Performance
- [ ] No N+1 queries
- [ ] Appropriate caching
- [ ] Lazy loading for heavy components
- [ ] Optimized images

### Documentation
- [ ] README with setup instructions
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Complex logic commented
- [ ] Environment variables documented

---

*This document should be referenced when building any software project to ensure production-quality output.*
