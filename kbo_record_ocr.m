#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) {
            fprintf(stderr, "usage: kbo_record_ocr IMAGE\n");
            return 2;
        }

        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSImage *image = [[NSImage alloc] initWithContentsOfFile:path];
        if (image == nil) {
            fprintf(stderr, "could not load image\n");
            return 3;
        }

        NSRect imageRect = NSMakeRect(0, 0, image.size.width, image.size.height);
        CGImageRef cgImage = [image CGImageForProposedRect:&imageRect context:nil hints:nil];
        if (cgImage == nil) {
            fprintf(stderr, "could not decode image\n");
            return 4;
        }

        VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
        request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        request.recognitionLanguages = @[@"ko-KR", @"en-US"];
        request.usesLanguageCorrection = YES;

        VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:cgImage options:@{}];
        NSError *error = nil;
        if (![handler performRequests:@[request] error:&error]) {
            fprintf(stderr, "OCR failed: %s\n", error.localizedDescription.UTF8String);
            return 5;
        }

        NSArray<VNRecognizedTextObservation *> *observations = [request.results sortedArrayUsingComparator:^NSComparisonResult(
            VNRecognizedTextObservation *left,
            VNRecognizedTextObservation *right
        ) {
            CGFloat verticalDelta = CGRectGetMidY(left.boundingBox) - CGRectGetMidY(right.boundingBox);
            if (fabs(verticalDelta) > 0.005) {
                return verticalDelta > 0 ? NSOrderedAscending : NSOrderedDescending;
            }
            CGFloat horizontalDelta = CGRectGetMinX(left.boundingBox) - CGRectGetMinX(right.boundingBox);
            if (horizontalDelta < 0) {
                return NSOrderedAscending;
            }
            if (horizontalDelta > 0) {
                return NSOrderedDescending;
            }
            return NSOrderedSame;
        }];

        for (VNRecognizedTextObservation *observation in observations) {
            VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
            if (candidate == nil) {
                continue;
            }
            NSString *text = [candidate.string stringByReplacingOccurrencesOfString:@"\t" withString:@" "];
            text = [text stringByReplacingOccurrencesOfString:@"\n" withString:@" "];
            CGRect box = observation.boundingBox;
            printf(
                "%.6f\t%.6f\t%.6f\t%.6f\t%s\n",
                box.origin.x,
                box.origin.y,
                box.size.width,
                box.size.height,
                text.UTF8String
            );
        }
    }
    return 0;
}
