Server and Client Components

By default, layouts and pages are Server Components
, which lets you fetch data and render parts of your UI on the server, optionally cache the result, and stream it to the client. When you need interactivity or browser APIs, you can use Client Components

to layer in functionality.

This page explains how Server and Client Components work in Next.js and when to use them, with examples of how to compose them together in your application.
When to use Server and Client Components?

The client and server environments have different capabilities. Server and Client components allow you to run logic in each environment depending on your use case.

Use Client Components when you need:

    State

and event handlers
. E.g. onClick, onChange.
Lifecycle logic
. E.g. useEffect.
Browser-only APIs. E.g. localStorage, window, Navigator.geolocation, etc.
Custom hooks

    .

Use Server Components when you need:

    Fetch data from databases or APIs close to the source.
    Use API keys, tokens, and other secrets without exposing them to the client.
    Reduce the amount of JavaScript sent to the browser.
    Improve the First Contentful Paint (FCP)

    , and stream content progressively to the client.

For example, the <Page> component is a Server Component that fetches data about a post, and passes it as props to the <LikeButton> which handles client-side interactivity.
app/[id]/page.tsx
TypeScript

import LikeButton from '@/app/ui/like-button'
import { getPost } from '@/lib/data'
 
export default async function Page({ params }: { params: { id: string } }) {
  const post = await getPost(params.id)
 
  return (
    <div>
      <main>
        <h1>{post.title}</h1>
        {/* ... */}
        <LikeButton likes={post.likes} />
      </main>
    </div>
  )
}

app/ui/like-button.tsx
TypeScript

'use client'
 
import { useState } from 'react'
 
export default function LikeButton({ likes }: { likes: number }) {
  // ...
}

How do Server and Client Components work in Next.js?
On the server

On the server, Next.js uses React's APIs to orchestrate rendering. The rendering work is split into chunks, by individual route segments (layouts and pages):

    Server Components are rendered into a special data format called the React Server Component Payload (RSC Payload).
    Client Components and the RSC Payload are used to prerender HTML.

    What is the React Server Component Payload (RSC)?

    The RSC Payload is a compact binary representation of the rendered React Server Components tree. It's used by React on the client to update the browser's DOM. The RSC Payload contains:

        The rendered result of Server Components
        Placeholders for where Client Components should be rendered and references to their JavaScript files
        Any props passed from a Server Component to a Client Component

On the client (first load)

Then, on the client:

    HTML is used to immediately show a fast non-interactive preview of the route to the user.
    RSC Payload is used to reconcile the Client and Server Component trees.
    JavaScript is used to hydrate Client Components and make the application interactive.

    What is hydration?

    Hydration is React's process for attaching event handlers

    to the DOM, to make the static HTML interactive.

Subsequent Navigations

On subsequent navigations:

    The RSC Payload is prefetched and cached for instant navigation.
    Client Components are rendered entirely on the client, without the server-rendered HTML.

Examples
Using Client Components

You can create a Client Component by adding the "use client"

directive at the top of the file, above your imports.
app/ui/counter.tsx
TypeScript

'use client'
 
import { useState } from 'react'
 
export default function Counter() {
  const [count, setCount] = useState(0)
 
  return (
    <div>
      <p>{count} likes</p>
      <button onClick={() => setCount(count + 1)}>Click me</button>
    </div>
  )
}

"use client" is used to declare a boundary between the Server and Client module graphs (trees).

Once a file is marked with "use client", all its imports and child components are considered part of the client bundle. This means you don't need to add the directive to every component that is intended for the client.
Reducing JS bundle size

To reduce the size of your client JavaScript bundles, add 'use client' to specific interactive components instead of marking large parts of your UI as Client Components.

For example, the <Layout> component contains mostly static elements like a logo and navigation links, but includes an interactive search bar. <Search /> is interactive and needs to be a Client Component, however, the rest of the layout can remain a Server Component.
app/layout.tsx
TypeScript

// Client Component
import Search from './search'
// Server Component
import Logo from './logo'
 
// Layout is a Server Component by default
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <nav>
        <Logo />
        <Search />
      </nav>
      <main>{children}</main>
    </>
  )
}

app/ui/search.tsx
TypeScript

'use client'
 
export default function Search() {
  // ...
}

Passing data from Server to Client Components

You can pass data from Server Components to Client Components using props.
app/[id]/page.tsx
TypeScript

import LikeButton from '@/app/ui/like-button'
import { getPost } from '@/lib/data'
 
export default async function Page({ params }: { params: { id: string } }) {
  const post = await getPost(params.id)
 
  return <LikeButton likes={post.likes} />
}

app/ui/like-button.tsx
TypeScript

'use client'
 
export default function LikeButton({ likes }: { likes: number }) {
  // ...
}

Alternatively, you can stream data from a Server Component to a Client Component with the use Hook

. See an example.

    Good to know: Props passed to Client Components need to be serializable

    by React.

Interleaving Server and Client Components

You can pass Server Components as a prop to a Client Component. This allows you to visually nest server-rendered UI within Client components.

A common pattern is to use children to create a slot in a <ClientComponent>. For example, a <Cart> component that fetches data on the server, inside a <Modal> component that uses client state to toggle visibility.
app/ui/modal.tsx
TypeScript

'use client'
 
export default function Modal({ children }: { children: React.ReactNode }) {
  return <div>{children}</div>
}

Then, in a parent Server Component (e.g.<Page>), you can pass a <Cart> as the child of the <Modal>:
app/page.tsx
TypeScript

import Modal from './ui/modal'
import Cart from './ui/cart'
 
export default function Page() {
  return (
    <Modal>
      <Cart />
    </Modal>
  )
}

In this pattern, all Server Components will be rendered on the server ahead of time, including those as props. The resulting RSC payload will contain references of where Client Components should be rendered within the component tree.
Context providers

React context

is commonly used to share global state like the current theme. However, React context is not supported in Server Components.

To use context, create a Client Component that accepts children:
app/theme-provider.tsx
TypeScript

'use client'
 
import { createContext } from 'react'
 
export const ThemeContext = createContext({})
 
export default function ThemeProvider({
  children,
}: {
  children: React.ReactNode
}) {
  return <ThemeContext.Provider value="dark">{children}</ThemeContext.Provider>
}

Then, import it into a Server Component (e.g. layout):
app/layout.tsx
TypeScript

import ThemeProvider from './theme-provider'
 
export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  )
}

Your Server Component will now be able to directly render your provider, and all other Client Components throughout your app will be able to consume this context.

    Good to know: You should render providers as deep as possible in the tree – notice how ThemeProvider only wraps {children} instead of the entire <html> document. This makes it easier for Next.js to optimize the static parts of your Server Components.

Third-party components

When using a third-party component that relies on client-only features, you can wrap it in a Client Component to ensure it works as expected.

For example, the <Carousel /> can be imported from the acme-carousel package. This component uses useState, but it doesn't yet have the "use client" directive.

If you use <Carousel /> within a Client Component, it will work as expected:
app/gallery.tsx
TypeScript

'use client'
 
import { useState } from 'react'
import { Carousel } from 'acme-carousel'
 
export default function Gallery() {
  const [isOpen, setIsOpen] = useState(false)
 
  return (
    <div>
      <button onClick={() => setIsOpen(true)}>View pictures</button>
      {/* Works, since Carousel is used within a Client Component */}
      {isOpen && <Carousel />}
    </div>
  )
}

However, if you try to use it directly within a Server Component, you'll see an error. This is because Next.js doesn't know <Carousel /> is using client-only features.

To fix this, you can wrap third-party components that rely on client-only features in your own Client Components:
app/carousel.tsx
TypeScript

'use client'
 
import { Carousel } from 'acme-carousel'
 
export default Carousel

Now, you can use <Carousel /> directly within a Server Component:
app/page.tsx
TypeScript

import Carousel from './carousel'
 
export default function Page() {
  return (
    <div>
      <p>View pictures</p>
      {/*  Works, since Carousel is a Client Component */}
      <Carousel />
    </div>
  )
}

    Advice for Library Authors

    If you’re building a component library, add the "use client" directive to entry points that rely on client-only features. This lets your users import components into Server Components without needing to create wrappers.

    It's worth noting some bundlers might strip out "use client" directives. You can find an example of how to configure esbuild to include the "use client" directive in the React Wrap Balancer

and Vercel Analytics

    repositories.

Preventing environment poisoning

JavaScript modules can be shared between both Server and Client Components modules. This means it's possible to accidentally import server-only code into the client. For example, consider the following function:
lib/data.ts
TypeScript

export async function getData() {
  const res = await fetch('https://external-service.com/data', {
    headers: {
      authorization: process.env.API_KEY,
    },
  })
 
  return res.json()
}

This function contains an API_KEY that should never be exposed to the client.

In Next.js, only environment variables prefixed with NEXT_PUBLIC_ are included in the client bundle. If variables are not prefixed, Next.js replaces them with an empty string.

As a result, even though getData() can be imported and executed on the client, it won't work as expected.

To prevent accidental usage in Client Components, you can use the server-only package

.

Then, import the package into a file that contains server-only code:
lib/data.js

import 'server-only'
 
export async function getData() {
  const res = await fetch('https://external-service.com/data', {
    headers: {
      authorization: process.env.API_KEY,
    },
  })
 
  return res.json()
}

Now, if you try to import the module into a Client Component, there will be a build-time error.

The corresponding client-only package

can be used to mark modules that contain client-only logic like code that accesses the window object.

In Next.js, installing server-only or client-only is optional. However, if your linting rules flag extraneous dependencies, you may install them to avoid issues.



Terminal

npm install server-only

Next.js handles server-only and client-only imports internally to provide clearer error messages when a module is used in the wrong environment. The contents of these packages from NPM are not used by Next.js.

Next.js also provides its own type declarations for server-only and client-only, for TypeScript configurations where noUncheckedSideEffectImports

is active.
Next Steps
Learn more about the APIs mentioned in this page.
