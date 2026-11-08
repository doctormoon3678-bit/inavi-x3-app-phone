#!/usr/bin/env bash
# Builds baksmali/dexlib2 2.5.2 from source with plain javac (no Maven needed)
# plus the OatDeodex driver.  Result: tools/build/out (classpath dir).
set -euo pipefail
T="$(cd "$(dirname "$0")" && pwd)"; B="$T/build"; mkdir -p "$B/src"; cd "$B/src"
clone() { [ -d "$3" ] || git -c advice.detachedHead=false clone -q --depth 1 -b "$2" "$1" "$3"; }
clone https://github.com/JesusFreke/smali v2.5.2 smali
clone https://github.com/google/guava v31.1 guava
clone https://github.com/cbeust/jcommander 1.64 jcommander
# compile-only annotation stubs used by guava
S=stubs; rm -rf $S
stub() { local pkg=${1%.*} cls=${1##*.}; mkdir -p $S/${pkg//.//}; echo "package $pkg; ${3:-} public @interface $cls { ${2:-} }" > $S/${pkg//.//}/$cls.java; }
for c in CanIgnoreReturnValue CheckReturnValue ForOverride MustBeClosed OverridingMethodsMustInvokeSuper; do stub com.google.errorprone.annotations.$c; done
for c in DoNotCall DoNotMock InlineMeValidationDisabled; do stub com.google.errorprone.annotations.$c 'String value() default "";'; done
stub com.google.errorprone.annotations.CompatibleWith 'String value();'
stub com.google.errorprone.annotations.Immutable 'String[] containerOf() default {};'
stub com.google.errorprone.annotations.InlineMe 'String replacement(); String[] imports() default {}; String[] staticImports() default {};'
stub com.google.errorprone.annotations.concurrent.GuardedBy 'String value() default "";'
stub com.google.errorprone.annotations.concurrent.LazyInit
for c in J2ObjCIncompatible RetainedWith Weak WeakOuter; do stub com.google.j2objc.annotations.$c; done
stub com.google.j2objc.annotations.ReflectionSupport 'Level value(); enum Level { NATIVE_ONLY, FULL }'
stub javax.annotation.CheckForNull; stub javax.annotation.Nullable
stub javax.annotation.Nonnull 'javax.annotation.meta.When when() default javax.annotation.meta.When.ALWAYS;'
stub javax.annotation.meta.TypeQualifierNickname
stub javax.annotation.meta.TypeQualifierDefault 'java.lang.annotation.ElementType[] value() default {};'
echo 'package javax.annotation.meta; public enum When { ALWAYS, UNKNOWN, MAYBE, NEVER }' > $S/javax/annotation/meta/When.java
for c in Nullable MonotonicNonNull NonNull PolyNull; do stub org.checkerframework.checker.nullness.qual.$c '' \
  '@java.lang.annotation.Target({java.lang.annotation.ElementType.TYPE_USE, java.lang.annotation.ElementType.TYPE_PARAMETER})'; done
find smali/dexlib2/src/main/java smali/util/src/main/java smali/baksmali/src/main/java -name '*.java' > files.txt
rm -rf "$B/out"; mkdir -p "$B/out"
javac -nowarn -proc:none -encoding UTF-8 -d "$B/out" \
  -sourcepath guava/guava/src:guava/futures/failureaccess/src:jcommander/src/main/java:$S @files.txt
cp smali/baksmali/src/main/resources/baksmali.properties "$B/out/"
javac -nowarn -proc:none -cp "$B/out" -d "$B/out" "$T/OatDeodex.java"
echo "built: $B/out"
