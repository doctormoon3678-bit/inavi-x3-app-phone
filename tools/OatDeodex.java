import com.google.common.collect.Lists;
import org.jf.baksmali.AnalysisArguments;
import org.jf.dexlib2.DexFileFactory;
import org.jf.dexlib2.Opcode;
import org.jf.dexlib2.Opcodes;
import org.jf.dexlib2.analysis.AnalyzedInstruction;
import org.jf.dexlib2.analysis.ClassPath;
import org.jf.dexlib2.analysis.MethodAnalyzer;
import org.jf.dexlib2.builder.BuilderInstruction;
import org.jf.dexlib2.builder.MutableMethodImplementation;
import org.jf.dexlib2.builder.instruction.*;
import org.jf.dexlib2.dexbacked.DexBackedDexFile;
import org.jf.dexlib2.iface.*;
import org.jf.dexlib2.iface.instruction.*;
import org.jf.dexlib2.iface.instruction.formats.*;
import org.jf.dexlib2.iface.MultiDexContainer;
import org.jf.dexlib2.immutable.ImmutableClassDef;
import org.jf.dexlib2.immutable.ImmutableMethod;
import org.jf.dexlib2.writer.io.FileDataStore;
import org.jf.dexlib2.writer.pool.DexPool;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * Deodexes an ART (Android 6.0, OAT v064) odex: extracts each embedded dex,
 * un-quickens odex-only instructions using the boot class path, and writes
 * a plain dex file (classes.dex, classes2.dex, ...) ready to go into the APK.
 *
 * usage: OatDeodex <app.odex> <out-dir> <boot.oat> [framework-dir]
 */
public class OatDeodex {
    static int fixed, unresolved;

    public static void main(String[] args) throws Exception {
        File odex = new File(args[0]);
        File outDir = new File(args[1]);
        outDir.mkdirs();
        MultiDexContainer<? extends DexBackedDexFile> container = DexFileFactory.loadDexContainer(odex, null);
        List<String> names = container.getDexEntryNames();
        for (int n = 0; n < names.size(); n++) {
            MultiDexContainer.DexEntry<? extends DexBackedDexFile> entry = container.getEntry(names.get(n));
            AnalysisArguments aa = new AnalysisArguments();
            aa.bootClassPath = Lists.newArrayList(args[2]);
            aa.classPathDirectories = Lists.newArrayList(args.length > 3 ? args[3] : new File(args[2]).getParent());
            ClassPath classPath = aa.loadClassPathForDexFile(odex.getAbsoluteFile().getParentFile(), entry, true);
            DexBackedDexFile dex = entry.getDexFile();

            DexPool pool = new DexPool(Opcodes.forApi(23));
            for (ClassDef cls : dex.getClasses()) {
                List<Method> methods = new ArrayList<>();
                for (Method m : cls.getMethods()) methods.add(deodex(classPath, m));
                pool.internClass(new ImmutableClassDef(cls.getType(), cls.getAccessFlags(), cls.getSuperclass(),
                        cls.getInterfaces(), cls.getSourceFile(), cls.getAnnotations(), cls.getFields(), methods));
            }
            String out = n == 0 ? "classes.dex" : "classes" + (n + 1) + ".dex";
            pool.writeTo(new FileDataStore(new File(outDir, out)));
            System.out.printf("%s -> %s (%d classes)%n", names.get(n), out, dex.getClasses().size());
        }
        System.out.printf("un-quickened %d instructions, %d unreachable replaced with throw%n", fixed, unresolved);
    }

    static Method deodex(ClassPath cp, Method m) {
        MethodImplementation impl = m.getImplementation();
        if (impl == null) return m;
        boolean odexed = false;
        for (Instruction i : impl.getInstructions()) if (i.getOpcode().odexOnly()) { odexed = true; break; }
        if (!odexed) return m;

        MethodAnalyzer ma = new MethodAnalyzer(cp, m, null, false);
        if (ma.getAnalysisException() != null)
            throw new RuntimeException("analysis failed: " + m, ma.getAnalysisException());
        MutableMethodImplementation mmi = new MutableMethodImplementation(impl);
        List<AnalyzedInstruction> ais = ma.getAnalyzedInstructions();
        for (int i = 0; i < ais.size(); i++) {
            AnalyzedInstruction ai = ais.get(i);
            if (!ai.getOriginalInstruction().getOpcode().odexOnly()) continue;
            Instruction d = ai.getInstruction();
            if (d.getOpcode().odexOnly()) {
                // dead code the analyzer could not reach: same as baksmali, replace with a throw
                int reg = ai.getOriginalInstruction() instanceof FiveRegisterInstruction
                        ? ((FiveRegisterInstruction) ai.getOriginalInstruction()).getRegisterC()
                        : ai.getOriginalInstruction() instanceof RegisterRangeInstruction
                        ? ((RegisterRangeInstruction) ai.getOriginalInstruction()).getStartRegister()
                        : ai.getOriginalInstruction() instanceof TwoRegisterInstruction
                        ? ((TwoRegisterInstruction) ai.getOriginalInstruction()).getRegisterB() : 0;
                mmi.replaceInstruction(i, new BuilderInstruction11x(Opcode.THROW, reg));
                unresolved++;
            } else {
                mmi.replaceInstruction(i, toBuilder(d));
                fixed++;
            }
        }
        return new ImmutableMethod(m.getDefiningClass(), m.getName(), m.getParameters(), m.getReturnType(),
                m.getAccessFlags(), m.getAnnotations(), m.getHiddenApiRestrictions(), mmi);
    }

    static BuilderInstruction toBuilder(Instruction d) {
        switch (d.getOpcode().format) {
            case Format10x: return new BuilderInstruction10x(d.getOpcode());
            case Format22c: {
                Instruction22c x = (Instruction22c) d;
                return new BuilderInstruction22c(d.getOpcode(), x.getRegisterA(), x.getRegisterB(), x.getReference());
            }
            case Format35c: {
                Instruction35c x = (Instruction35c) d;
                return new BuilderInstruction35c(d.getOpcode(), x.getRegisterCount(), x.getRegisterC(),
                        x.getRegisterD(), x.getRegisterE(), x.getRegisterF(), x.getRegisterG(), x.getReference());
            }
            case Format3rc: {
                Instruction3rc x = (Instruction3rc) d;
                return new BuilderInstruction3rc(d.getOpcode(), x.getStartRegister(), x.getRegisterCount(),
                        x.getReference());
            }
            default: throw new IllegalStateException("unexpected deodexed format " + d.getOpcode());
        }
    }
}
